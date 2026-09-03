"""Re-embed a persistent memory store against a different embedder (ADR-0104).

ADR-0006 §4 tags every stored vector
with the model that produced it, so ``SqliteMemoryStore`` refuses to open a store
built by a different embedder rather than ranking incomparable vectors against
each other. The refusal is right and stays; this module is the migration it has
been demanding since #425 — the half ADR-0006 §4 promised when it said the
metadata exists so the store can "drive that migration".

**Build-and-swap, never in place** (ADR-0104 §1). Halfway through an in-place
rewrite a store holds vectors from two embedding spaces under one ``meta`` row,
which is precisely the condition ADR-0006 §4's per-*store* tag cannot detect, so
every search served from it is silently wrong with nothing on disk saying so.
Here the live file is never written: a work store is built beside it, verified
against it, and moved into place with one ``os.replace``. Every crash leaves
either the old store or the new one, both internally consistent.

**Resumable by construction** (ADR-0104 §2), because a store with months of
records re-embedded by a CPU-bound on-device model is a job long enough that an
interruption is the expected case, not the exceptional one. Each chunk's rows,
their vectors and the cursor naming the last source ``rowid`` copied commit in one
transaction, so a recorded cursor can never claim progress the work store does not
hold.

**It reads content, never the old vectors**, which is why no source embedder is
constructed anywhere here — and therefore why a deployment can migrate *off* an
embedder it can no longer build at all. It reads the four columns that have
existed since the schema's first version and derives the rest from each record's
stored JSON, so a store the current build has never opened migrates without its
schema being brought forward first — which would mean writing to the live store,
and ADR-0104 §1 forbids that. The one exception is a record's ``revision``, which
is store-authored and deliberately outside the payload (ADR-0219 §1) and so cannot
be derived from anything: it is carried across verbatim where the source has it,
issued from the work store's own issuer where the source predates the column, and
the source's issuer is carried with it (§10).

Nothing here takes the instance lock or decides whether the target embedder is an
acceptable one. Both belong to the entry point and the composition root
respectively (ADR-0104 §5): this module receives an ``Embedder`` and cannot tell
where it runs, and must not be asked to guess.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import stat
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, NoReturn

import sqlite_vec

from ai_assistant.core.errors import (
    EmbeddingDeadlineExpiredError,
    IncompatibleStateError,
    MemoryStoreEmbeddingExpiredError,
    MemoryStoreError,
)
from ai_assistant.memory._transactions import transaction
from ai_assistant.memory.sqlite_store import _ADAPTER, SqliteMemoryStore, _to_micros

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from ai_assistant.core.protocols import Embedder
    from ai_assistant.core.types import Embedding, EvaluationTrace, MemoryRecord

#: Appended to the live store's name for the store being built beside it. A
#: sibling rather than a temporary directory because ``os.replace`` is atomic only
#: within one filesystem, and same-directory is the only placement that guarantees
#: that without probing (ADR-0104 §1).
WORK_SUFFIX: Final = ".reembed"

#: Appended for the retained pre-migration store (ADR-0104 §3). It is a hard link
#: to the original inode, so retaining it costs no copy, and deleting it is the
#: operator's act rather than this module's.
BACKUP_SUFFIX: Final = ".pre-reembed"

#: How many records are embedded and committed per transaction. Batching is what
#: ``Embedder.embed`` exists for — embedding amortises over a batch — and the
#: transaction boundary is what ADR-0104 §2's resumability is measured in, so the
#: two are deliberately the same number.
DEFAULT_BATCH_SIZE: Final = 128

#: The work store's ``meta`` key holding the last source ``rowid`` copied.
#: **Absent until the first chunk commits**, which is how "nothing copied yet" is
#: spelled. A sentinel would have to be an integer below every possible ``rowid``,
#: and SQLite has none: ``rowid`` starts at ``-2**63``, so ``0`` — the obvious
#: choice — silently skips every row at or below it.
_CURSOR_KEY: Final = "reembed_cursor"

#: The work store's ``meta`` key holding the fingerprint of the live store the
#: copy was started from (ADR-0104 §2).
_SOURCE_KEY: Final = "reembed_source"

#: The keys a finished store's ``meta`` holds, and the only ones. ADR-0104 §2
#: requires the scaffolding above to be gone before the swap, and §3's
#: verification asserts exactly this set — a store's identity is written down in
#: one place or the property stops being checkable.
_STORE_META_KEYS: Final = frozenset({"embedding_model", "dimensions"})

#: The sidecars SQLite may keep beside a database file. Mirrors the tuple in
#: ``memory/sqlite_store.py``, which uses it for a different purpose (restricting
#: their mode); duplicated rather than shared because the two lists answer
#: different questions and would not move together.
_SIDECARS: Final = ("-journal", "-wal", "-shm")

#: The file change counter's bytes in the SQLite header — a big-endian 32-bit
#: integer SQLite increments whenever it unlocks a database it has modified
#: (`the database file format <https://sqlite.org/fileformat2.html>`_). Read as
#: opaque bytes rather than decoded: :func:`_fingerprint` only ever compares it
#: with itself.
_CHANGE_COUNTER_START: Final = 24
_CHANGE_COUNTER_END: Final = 28

#: The columns that have existed in ``records`` since the schema's first version,
#: plus the one column this migration cannot re-derive: a record's ``revision`` is
#: store-authored and is deliberately **not** in its payload (ADR-0219 §1), so a
#: rebuild that read only the blob would drop every stamp at the swap and start the
#: swapped store on a fresh issuer — reissuing every value the old store had handed
#: out, through an ordinary operational migration rather than through any write
#: (§10).
_SOURCE_COLUMNS: Final = "rowid, id, kind, data, revision"

#: The same read against a store written before that column existed. ``NULL`` in the
#: stamp's place is how "this row has no stamp to carry" is spelled, and
#: :func:`_insert` issues one from the work store's own issuer for it — which is
#: sound precisely because the work store is a *new* store whose issuer has issued
#: nothing, so §1's never-reissued clause is satisfied by construction.
_LEGACY_SOURCE_COLUMNS: Final = "rowid, id, kind, data, NULL"

#: Where the stamp sits in a source row read through either of the two above.
_REVISION_IN_ROW: Final = 4

#: One row as ``sqlite3`` hands it over. The driver types every column ``Any``, so
#: naming that here keeps the alias honest rather than asserting a shape the
#: driver does not promise.
type _Row = tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class ReembedPlan:
    """What a run would do, computed before it does any of it."""

    store: Path
    """The live store this plan is about."""

    work: Path
    """Where the re-embedded store is built."""

    backup: Path
    """Where the pre-migration store is retained."""

    source_model: str
    """The embedding model the live store records."""

    source_dimensions: int
    """The vector width the live store records."""

    target_model: str
    """The embedding model the run would leave behind."""

    target_dimensions: int
    """The vector width the run would leave behind."""

    records: int
    """How many records the live store holds."""

    resumable: int
    """How many of them a previous run already re-embedded and this one may keep."""

    @property
    def required(self) -> bool:
        """Whether anything needs doing: the store's tag differs from the target's."""
        return (self.source_model, self.source_dimensions) != (
            self.target_model,
            self.target_dimensions,
        )

    @property
    def outstanding(self) -> int:
        """How many records this run would have to embed."""
        return max(self.records - self.resumable, 0)


@dataclass(frozen=True, slots=True)
class ReembedOutcome:
    """What a finished run did."""

    plan: ReembedPlan
    """The plan the run was started from."""

    embedded: int
    """Records embedded by this run."""

    resumed: int
    """Records inherited from an earlier, interrupted run."""

    swapped: bool
    """Whether the live store was replaced. ``False`` when nothing was required."""

    durable: bool
    """Whether the rename was confirmed flushed to disk.

    ``False`` says the swap **happened** and could not be *confirmed* durable —
    directory ``fsync`` is refused outright on some filesystems — which is a
    different fact from the swap failing and must be reported as one. A caller
    that reports it as a failure sends an operator looking for a store that no
    longer exists.
    """


def _fingerprint(store: Path) -> str:
    """Identify the live store's *current* content, cheaply (ADR-0104 §2).

    The question this answers is not "is this the same file" but "has anything
    written to it since the last attempt" — because a resumed scan starts past the
    cursor and never revisits a row updated or deleted below it, so a source that
    moved under a half-built copy makes that copy stale in a way no later chunk
    corrects.

    **Device, inode, size and mtime are not enough on their own, and the reason is
    not exotic.** ``st_mtime_ns`` reports the filesystem's timestamp *resolution*,
    not a promise that two writes a microsecond apart get different values: Linux
    stamps inodes from a coarse clock, so a same-sized update inside one tick can
    leave all four unchanged. So the SQLite **file change counter** is read too —
    the four bytes at offset 24 of the header, which SQLite increments whenever it
    unlocks a database it has modified. It moves on a write that changes no byte
    of the file's length and no timestamp, which is exactly the case the stat
    fields miss. (WAL updates it differently, which costs nothing here: a WAL
    store is refused outright by :func:`_require_rollback_journal`.)

    Deliberately conservative: it re-runs the whole migration on any doubt, since
    a false restart costs CPU and a false resume costs a corrupt store. It is also
    not the last word for a resume — :func:`_verify` re-reads both stores in full
    and does not consult it.

    Raises:
        MemoryStoreError: If the header cannot be read at all.
    """
    info = store.stat()
    try:
        with store.open("rb") as handle:
            header = handle.read(_CHANGE_COUNTER_END)
    except OSError as exc:
        msg = f"failed to read the header of {store}: {exc}"
        raise MemoryStoreError(msg) from exc
    counter = header[_CHANGE_COUNTER_START:_CHANGE_COUNTER_END].hex()
    return f"{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}:{counter}"


def _connect(path: Path) -> sqlite3.Connection:
    """Open ``path`` with ``sqlite-vec`` loaded, translating failures.

    Raises:
        MemoryStoreError: If the database cannot be opened or the extension
            cannot be loaded.
    """
    try:
        conn = sqlite3.connect(str(path), isolation_level=None)
    except (sqlite3.Error, OSError, ValueError) as exc:
        # ``ValueError`` is named because a path carrying an embedded NUL raises it
        # out of the driver rather than a ``sqlite3.Error``, and a bad path is this
        # layer's fault to report rather than a raw builtin escaping past the
        # ``MemoryStoreError`` boundary this function documents (#1933).
        msg = f"failed to open {str(path)!r}: {exc}"
        raise MemoryStoreError(msg) from exc
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except (sqlite3.Error, OSError) as exc:
        conn.close()
        msg = f"failed to load the vector extension for {str(path)!r}: {exc}"
        raise MemoryStoreError(msg) from exc
    return conn


def _read_meta(conn: sqlite3.Connection, what: str) -> dict[str, str]:
    """Read a store's whole ``meta`` table.

    Raises:
        MemoryStoreError: If the table cannot be read, which is what an ordinary
            file that is not a memory store presents as.
    """
    try:
        rows = conn.execute("SELECT key, value FROM meta").fetchall()
    except sqlite3.Error as exc:
        msg = f"{what} is not a memory store, or its metadata cannot be read: {exc}"
        raise MemoryStoreError(msg) from exc
    return {str(key): str(value) for key, value in rows}


def _count(conn: sqlite3.Connection, table: str, what: str) -> int:
    """Count the rows in ``table``.

    Raises:
        MemoryStoreError: If the table cannot be read.
    """
    sql = f"SELECT COUNT(*) FROM {table}"  # noqa: S608 — a module-level literal, never caller data
    try:
        (count,) = conn.execute(sql).fetchone()
    except sqlite3.Error as exc:
        msg = f"failed to count {table} in {what}: {exc}"
        raise MemoryStoreError(msg) from exc
    return int(count)


def _highest_copied(conn: sqlite3.Connection, work: Path) -> int | None:
    """The largest ``rowid`` a work store holds, or ``None`` when it holds none.

    ``_insert`` carries the source ``rowid`` across unchanged and ``_chunk`` reads
    in ``rowid`` order, so this is the source row the last committed chunk
    reached — the same fact the cursor records, read from the rows themselves.

    Raises:
        MemoryStoreError: If the table cannot be read.
    """
    try:
        (highest,) = conn.execute("SELECT MAX(rowid) FROM records").fetchone()
    except sqlite3.Error as exc:
        msg = f"failed to read the highest copied rowid in {work}: {exc}"
        raise MemoryStoreError(msg) from exc
    return None if highest is None else int(highest)


def _as_int(value: str, what: str) -> int:
    """Read a number out of a store's ``meta``, as this seam's error rather than a crash.

    Every value in ``meta`` is text somebody could have edited, and the console
    tool above this maps ``AssistantError`` to an exit code and lets anything else
    become a traceback. A store whose ``dimensions`` says ``'unknown'`` is a store
    this build cannot reason about, which is a thing to *report*, not to fall over.

    Raises:
        MemoryStoreError: If the value is not an integer.
    """
    try:
        return int(value)
    except ValueError as exc:
        msg = f"{what} is {value!r}, which is not a number"
        raise MemoryStoreError(msg) from exc


def _decode(data: str, record_id: object) -> MemoryRecord:
    """Decode a stored record, naming the row when it will not decode.

    The migration decodes every record rather than shovelling bytes, for two
    reasons that both matter: the text to embed is a *field* of the record, and
    the destination's derived columns must be the ones the store's own write path
    would produce — which are read off the decoded model, not re-parsed out of the
    JSON. A record that no longer decodes is already unreadable through every one
    of the store's read paths, so failing here, loudly and by id, is strictly
    better than copying it into the new store unexamined.

    Raises:
        MemoryStoreError: If the stored JSON is not a valid record.
    """
    try:
        return _ADAPTER.validate_json(data)
    except Exception as exc:
        msg = f"the record stored as {record_id!r} could not be decoded: {exc}"
        raise MemoryStoreError(msg) from exc


def _derived(record: MemoryRecord) -> tuple[int | None, int | None, int | None, str | None]:
    """The lifecycle, window and subject columns, as the store's write path derives them.

    Kept in this shape — read off the decoded model, not re-parsed from the JSON —
    so it cannot drift from ``SqliteMemoryStore._persist_record``, which is the
    only other place these values are computed.

    **``valid_from`` is here because dropping it hides nothing and reveals
    everything.** ADR-0128 §1 binds that end of the window before ``search``'s
    ranking cut, which it can only do from a column; a rebuild that carried the
    blob and left the column ``NULL`` would leave the *read* wrong while every
    record round-tripped intact, because ``NULL`` is an open window. That is the
    quietest failure this module can produce — a not-yet-live record becomes
    searchable on a store that was only re-embedded — so :func:`_verify` compares
    this tuple against the blob for every row before anything is moved.
    """
    expires = _to_micros(record.expires_at) if record.expires_at is not None else None
    valid_until = (
        _to_micros(record.validity.valid_until) if record.validity.valid_until is not None else None
    )
    valid_from = (
        _to_micros(record.validity.valid_from) if record.validity.valid_from is not None else None
    )
    return expires, valid_until, valid_from, record.about_person


def _discard(path: Path) -> None:
    """Remove a database file and any sidecar beside it, tolerating absence."""
    for candidate in (path, *(path.with_name(path.name + suffix) for suffix in _SIDECARS)):
        with contextlib.suppress(FileNotFoundError):
            candidate.unlink()


def _require_no_sidecars(store: Path) -> None:
    """Refuse a store that has a SQLite sidecar beside it (ADR-0104 §3).

    Checked **before** the store is opened, which is what makes it mean anything:
    a cleanly closed database in this project's journal mode has no sidecar, so
    one lying beside it says either that a process is using the file right now or
    that one died holding it. Both are states this migration must not build a copy
    from and must never rename over — a ``-wal`` holding committed pages would be
    orphaned against a different database by the swap, which is not a failure
    anything downstream could detect.

    The instance lock the entry point holds excludes the live hub (ADR-0083 §1,
    §10); this catches what the lock cannot, since the lock is advisory.

    Raises:
        IncompatibleStateError: If any sidecar is present.
    """
    for suffix in _SIDECARS:
        sidecar = store.with_name(store.name + suffix)
        if sidecar.exists():
            msg = (
                f"{sidecar} is present beside {store}, so the store is either open in "
                f"another process or was left behind by one that died holding it"
            )
            raise IncompatibleStateError(
                msg,
                expected=f"no {suffix} file beside {store.name}",
                found=str(sidecar),
                operator_action=(
                    f"stop whatever has {store} open, then run the migration again; if "
                    f"nothing has it open, start and cleanly stop the hub to let SQLite "
                    f"retire {sidecar}"
                ),
            )


def _require_rollback_journal(conn: sqlite3.Connection, store: Path) -> None:
    """Refuse a store in WAL mode, which this migration cannot safely replace (ADR-0104 §3).

    Journal mode is a property of the database header and survives a close, so a
    WAL store presents as sidecar-free until it is opened. Replacing it by rename
    would leave its ``-wal`` beside a *different* database for SQLite to recover
    against, and the pages in it would be lost or, worse, applied. WAL is deferred
    by ADR-0083 §12 with reasons and tracked as #505, so no store this build wrote
    is in it; this is the check that says so rather than assuming it.

    Raises:
        IncompatibleStateError: If the store is in WAL mode.
        MemoryStoreError: If the mode cannot be read.
    """
    try:
        (mode,) = conn.execute("PRAGMA journal_mode").fetchone()
    except sqlite3.Error as exc:
        msg = f"failed to read the journal mode of {store}: {exc}"
        raise MemoryStoreError(msg) from exc
    if str(mode).lower() == "wal":
        msg = f"{store} is in WAL mode, which this migration cannot safely replace by rename"
        raise IncompatibleStateError(
            msg,
            expected="a rollback-journal store",
            found=f"journal_mode={mode}",
            operator_action=(
                f"take {store} out of WAL mode (`PRAGMA journal_mode=DELETE`) with the hub "
                f"stopped, then run the migration again"
            ),
        )


class _DiscardedTraces:
    """The sink for a store that is opened to run DDL and closed again.

    Structurally satisfies :class:`~ai_assistant.core.protocols.TraceSink`.
    ADR-0119 §7 makes a sink a required constructor argument so that "a
    composition that omits it does not type-check", against the failure where "an
    unwired emitter produces no traces, and no traces is indistinguishable from no
    events". That failure needs an emitter with events to lose;
    :meth:`Reembedder._prepare_work`'s store never serves a read, so it has none.
    Deliberately module-private, so nothing outside this file can wire it.
    """

    async def emit(self, trace: EvaluationTrace) -> None:
        """Discard ``trace``.

        Args:
            trace: The trace no read produced, since no read runs on this store.
        """


class Reembedder:
    """Rebuilds one memory store's vectors against a new embedder (ADR-0104).

    One instance covers one store and one target embedder. It opens the live
    store read-only in effect — every statement it issues against it is a
    ``SELECT`` — and does all its writing in a sibling file until the final swap.
    """

    def __init__(
        self,
        *,
        store: Path,
        embedder: Embedder,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        """Prepare a migration without touching anything.

        Args:
            store: The live memory store, normally ``<data_dir>/memory.db``.
            embedder: The embedder the store should be built against after the
                run. Whether it is an acceptable target is decided above this
                seam (ADR-0104 §4, §5).
            batch_size: How many records are embedded and committed at a time.

        Raises:
            ValueError: If ``batch_size`` is not at least one, which would make
                the copy loop unable to advance.
        """
        if batch_size < 1:
            msg = f"batch_size must be >= 1, got {batch_size}"
            raise ValueError(msg)
        self._store = Path(store)
        self._work = self._store.with_name(self._store.name + WORK_SUFFIX)
        self._backup = self._store.with_name(self._store.name + BACKUP_SUFFIX)
        self._embedder = embedder
        self._batch_size = batch_size

    @property
    def store(self) -> Path:
        """The live store this migration is about, for a caller that must report it."""
        return self._store

    def plan(self) -> ReembedPlan:
        """Report what a run would do, without doing any of it.

        Also the pre-flight: it is where a store that is missing, unreadable, in
        an unsafe journal mode, or already current is found out, before hours of
        embedding are spent.

        Raises:
            MemoryStoreError: If the store is absent or its metadata cannot be
                read.
            IncompatibleStateError: If a SQLite sidecar lies beside the store or
                it is in WAL mode (ADR-0104 §3).
        """
        if not self._store.is_file():
            msg = f"there is no memory store at {self._store}"
            raise MemoryStoreError(msg)
        _require_no_sidecars(self._store)
        conn = _connect(self._store)
        try:
            _require_rollback_journal(conn, self._store)
            meta = _read_meta(conn, str(self._store))
            records = _count(conn, "records", str(self._store))
        finally:
            conn.close()
        source_model = meta.get("embedding_model")
        source_dimensions = meta.get("dimensions")
        if source_model is None or source_dimensions is None:
            msg = (
                f"{self._store} records no embedding model, so there is nothing to "
                f"migrate from; it is not a memory store this build wrote"
            )
            raise MemoryStoreError(msg)
        return ReembedPlan(
            store=self._store,
            work=self._work,
            backup=self._backup,
            source_model=source_model,
            source_dimensions=_as_int(source_dimensions, f"the dimension {self._store} records"),
            target_model=self._embedder.model_id,
            target_dimensions=self._embedder.dimensions,
            records=records,
            resumable=self._resumable(),
        )

    def _resumable(self) -> int:
        """How many rows of an existing work store this run may keep (ADR-0104 §2)."""
        inheritable = self._inheritable()
        return 0 if inheritable is None else inheritable[0]

    def _inheritable(self) -> tuple[int, int] | None:
        """The rows and cursor of a work store this run may continue from (ADR-0104 §2).

        ``None`` whenever the work store is absent or unreadable, was built for a
        different target, was started from a live store that has since changed, or
        records a cursor that does not account for the rows it holds. §2 names the
        first of those conditions and discards rather than adapts on each; the last
        is the same answer applied to the same kind of state, and the whole of what
        this method decides is **usable or not**.

        §2 commits each chunk's rows and the cursor naming the last source ``rowid``
        copied in one transaction, "so the recorded cursor can never claim progress
        the work store does not hold". That invariant is checked here rather than
        assumed, because damage from outside this module can break it and every way
        of breaking it resumes into rows that are already there: the copy restarts
        at a source row the work store already holds, the insert collides, and the
        retry fails identically for as long as the file survives (#738).

        Returns:
            The row count and the cursor to continue past, or ``None`` when there
            is nothing to continue from — an untouched work store included, whose
            rows and cursor agree by both being absent.
        """
        if not self._work.is_file():
            return None
        try:
            conn = _connect(self._work)
        except MemoryStoreError:
            return None
        try:
            meta = _read_meta(conn, str(self._work))
            continuable = meta.get(_SOURCE_KEY) == _fingerprint(self._store)
            same_target = (meta.get("embedding_model"), meta.get("dimensions")) == (
                self._embedder.model_id,
                str(self._embedder.dimensions),
            )
            if not (continuable and same_target):
                return None
            # Parsed here rather than trusted at resume time: an unreadable cursor
            # is one more way to be unusable, and it takes the same exit.
            recorded = meta.get(_CURSOR_KEY)
            cursor = (
                None if recorded is None else _as_int(recorded, f"the cursor {self._work} records")
            )
            if cursor is None or cursor != _highest_copied(conn, self._work):
                return None
            return _count(conn, "records", str(self._work)), cursor
        except MemoryStoreError:
            return None
        finally:
            conn.close()

    async def run(self, *, progress: Callable[[int, int], None] | None = None) -> ReembedOutcome:
        """Re-embed the store and swap the result in.

        Args:
            progress: Called after each committed chunk with the number of records
                copied so far and the total. A long run is otherwise
                indistinguishable from a stuck one.

        Returns:
            What the run did. A store already carrying the target's tag is
            reported as requiring nothing, and nothing is written.

        Raises:
            MemoryStoreError: If the store cannot be read, a record cannot be
                decoded, the embedder fails or returns a wrong-shaped batch, or
                verification fails. In every case the live store is untouched.
            IncompatibleStateError: If the store has a sidecar beside it or is in
                WAL mode, or the retained-original path is occupied by something
                that is not this store (ADR-0104 §3).
        """
        plan = self.plan()
        if not plan.required:
            return ReembedOutcome(plan=plan, embedded=0, resumed=0, swapped=False, durable=True)
        started = _fingerprint(self._store)
        # What this run inherits is what the work store is observed to hold when the
        # copy is about to start, not what the plan counted a moment earlier: the
        # plan can be stale in either direction, and `_prepare_work` may itself have
        # discarded the store the plan was counting (#738).
        resumed, cursor = self._prepare_work(plan.resumable)
        source = _connect(self._store)
        try:
            work = _connect(self._work)
            try:
                columns = _source_columns(source, self._store)
                embedded = await self._copy(source, work, cursor, resumed, plan, progress, columns)
                self._finalise(source, work)
                _verify(source, work, plan, self._embedder, columns)
            finally:
                work.close()
        finally:
            source.close()
        durable = self._swap(started)
        return ReembedOutcome(
            plan=plan, embedded=embedded, resumed=resumed, swapped=True, durable=durable
        )

    def _prepare_work(self, resumed: int) -> tuple[int, int | None]:
        """Return the rows inherited and the cursor to continue from.

        The work store is created here if there is nothing to inherit. Both
        returned figures come from :meth:`_inheritable`, read at this call rather
        than taken from the plan, because this is the last point before the copy
        begins; the caller's ``resumed`` is the plan's count and decides only
        whether to look at all. Taking them from the plan would mis-state
        ``resumed`` and every progress call whenever the work store moved under it
        (#738). A plan that already found nothing to keep is honoured as it
        stands — re-deciding it here could only turn a discard into a resume,
        which is the direction §2 refuses to guess in.

        The work store is created by constructing a :class:`SqliteMemoryStore` on
        it and closing it again, rather than by repeating its DDL here. That is
        the point: the destination is then whatever the current schema is, meta
        included, and it stays that way when the schema next changes.

        **The sink it is handed is a discard**, and that is honest rather than a
        loophole in ADR-0119 §7's required-constructor rule. This store is opened
        to run DDL and closed on the next expression; it never serves a ``search``,
        so it can emit nothing and there is nothing for a sink to receive. Wiring
        a real one would mean threading a ``TraceSink`` through
        :func:`~ai_assistant.app.build_reembedder` and the offline migration entry
        point to reach a code path that cannot use it.
        """
        if resumed:
            inheritable = self._inheritable()
            if inheritable is not None:
                return inheritable
            # One decision, asked again at the last moment before the copy. The plan
            # said there was something to keep and there no longer is, so the work
            # store moved under it; fall through to the discard rather than copy
            # into rows that are already there (#738).
        _discard(self._work)
        SqliteMemoryStore(
            path=self._work, embedder=self._embedder, traces_sink=_DiscardedTraces()
        ).close()
        conn = _connect(self._work)
        try:
            with transaction(conn, "start a re-embedding", error=MemoryStoreError):
                _write_meta(conn, _SOURCE_KEY, _fingerprint(self._store))
        finally:
            conn.close()
        return 0, None

    async def _copy(  # noqa: PLR0913 — one argument per collaborator this loop needs
        self,
        source: sqlite3.Connection,
        work: sqlite3.Connection,
        cursor: int | None,
        resumed: int,
        plan: ReembedPlan,
        progress: Callable[[int, int], None] | None,
        columns: str,
    ) -> int:
        """Copy every record past ``cursor``, one committed chunk at a time.

        ``resumed`` is what the work store was observed to carry in, which is the
        plan's figure only when the plan was still true at ``_prepare_work``;
        progress counts from it rather than from the plan so that what is reported
        is the rows this store actually holds.
        """
        embedded = 0
        while True:
            rows = _chunk(source, cursor, self._batch_size, columns)
            if not rows:
                return embedded
            records = [_decode(str(row[3]), row[1]) for row in rows]
            vectors = await self._embed([record.content for record in records])
            cursor = int(rows[-1][0])
            with transaction(work, "copy a re-embedded chunk", error=MemoryStoreError):
                for row, record, vector in zip(rows, records, vectors, strict=True):
                    _insert(work, row, record, vector)
                _write_meta(work, _CURSOR_KEY, str(cursor))
            embedded += len(rows)
            if progress is not None:
                progress(resumed + embedded, plan.records)

    async def _embed(self, texts: Sequence[str]) -> list[Embedding]:
        """Embed a chunk, mapping any embedder misbehaviour to our error.

        The embedder is an injected contract, so a provider fault, a wrong batch
        cardinality or a wrong-width vector must surface as ``MemoryStoreError``
        rather than an arbitrary exception escaping this seam — the shape
        ``SqliteMemoryStore._embed_one`` already uses, applied to a batch.

        **Including its expiry arm** (ADR-0118 §5's second clause): a chunk whose
        embedding outlived the bounded embedder's deadline raises
        ``MemoryStoreEmbeddingExpiredError`` with the seam's own class as the
        cause, so an operator watching a migration stall can tell a wedged
        embedding backend from a broken store without reading a message. The
        migration is bounded by that deadline even though ADR-0104 §6 keeps it
        outside the scheduler, because it is wired the same embedder (ADR-0118 §8).

        Raises:
            MemoryStoreEmbeddingExpiredError: If an embedding outlived its
                deadline. A ``MemoryStoreError``, so the run aborts as it always
                did — the half-built work store is left for a resumed run, exactly
                as any other mid-chunk failure leaves it.
            MemoryStoreError: If the embedder fails or returns the wrong shape.
        """
        try:
            vectors = list(await self._embedder.embed(texts))
            if len(vectors) != len(texts):
                msg = f"embedder returned {len(vectors)} vectors for {len(texts)} texts"
                raise MemoryStoreError(msg)
            for vector in vectors:
                if len(vector) != self._embedder.dimensions:
                    msg = (
                        f"embedder returned a {len(vector)}-dim vector, "
                        f"expected {self._embedder.dimensions}"
                    )
                    raise MemoryStoreError(msg)
        except MemoryStoreError:
            raise
        except EmbeddingDeadlineExpiredError as exc:
            # Ahead of the general arm below, which would otherwise absorb it.
            msg = f"embedding a re-embedding chunk outlived its deadline: {exc}"
            raise MemoryStoreEmbeddingExpiredError(msg) from exc
        except Exception as exc:  # any fault or malformed result from the embedder
            msg = f"embedder failed: {exc}"
            raise MemoryStoreError(msg) from exc
        return vectors

    def _finalise(self, source: sqlite3.Connection, work: sqlite3.Connection) -> None:
        """Delete the migration scaffolding and carry the revision issuer across.

        The scaffolding goes so the swapped-in store carries none. The **issuer**
        comes with it because ADR-0219 §1 scopes "never reissued" to the life of the
        data a durable store holds, and a build-and-swap does not end that life: the
        swapped store holds the same records, so it must not hand out a stamp the
        replaced store already did. Copying the rows carries every stamp that is
        *present*; the issuer is what records the ones that are not — the values
        deleted rows took — and reconstructing it from the rows present is precisely
        what §1 forbids.

        Raised to the source's mark rather than set to it, so the work store's own
        issuing (a legacy source, whose rows are stamped here) is never walked back.
        A source with no issuer at all is a store written before this column existed
        and has none to carry.
        """
        with transaction(work, "finish a re-embedding", error=MemoryStoreError):
            work.execute(
                "DELETE FROM meta WHERE key IN (?, ?)",
                (_CURSOR_KEY, _SOURCE_KEY),
            )
            work.execute(
                "UPDATE revision_issuer SET issued = MAX(issued, ?) WHERE singleton = 0",
                (_issued_through(source),),
            )

    def _swap(self, started: str) -> bool:
        """Re-check the source, retain it, then move the verified store into place.

        Both connections are closed by the time this runs, and the store was
        cleared of sidecars and of WAL mode before any of the work started
        (:meth:`plan`), which is what makes the rename safe. The order — link,
        then replace — is what keeps the swap a single atomic step while still
        retaining the original: an interruption between the two leaves the live
        store intact and a hard link to it that the next run recognises as its
        own (ADR-0104 §3).

        **The source is fingerprinted once more first**, and that is a narrowing
        rather than a guarantee. Verification and the rename are two steps, and
        anything writing to the live store between them would have its write
        thrown away by the rename with nothing reporting it. The instance lock
        stops the hub, but it is advisory — ADR-0083 §10 says so — so it does not
        stop a ``sqlite3`` shell somebody left open on their own machine, which is
        the case this actually catches. What is left is the gap between this stat
        and the rename below, which is microseconds rather than the length of a
        full re-read.

        Args:
            started: The source's fingerprint when the run began.

        Raises:
            IncompatibleStateError: If the retained-original path names something
                that is not this store.
            MemoryStoreError: If the source changed while the copy was built, or
                the link or the rename fails.

        Returns:
            Whether the rename was confirmed flushed to disk. ``False`` means the
            swap happened and its durability could not be confirmed.
        """
        if _fingerprint(self._store) != started:
            msg = (
                f"{self._store} changed while the re-embedded store was being built, so "
                f"the re-embedded store is missing that change and was not swapped in"
            )
            raise MemoryStoreError(msg)
        self._retain()
        try:
            self._work.replace(self._store)
        except OSError as exc:
            msg = f"failed to move the re-embedded store into place at {self._store}: {exc}"
            raise MemoryStoreError(msg) from exc
        # Past this line the migration has *happened*, so a failure below is a
        # failure to confirm durability and is reported as one rather than raised.
        # Directory `fsync` is refused outright on some filesystems, which is a
        # property of the mount rather than a fault of this run — and an operator
        # told "the swap did not happen", over a store that now carries the new
        # tag, would go looking for a store that no longer exists.
        try:
            directory = os.open(str(self._store.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            return False
        return True

    def _retain(self) -> None:
        """Hard-link the live store to its retained-original path (ADR-0104 §3).

        An existing path that is a **hard link to this store's own inode** is a
        previous attempt's, interrupted between the link and the rename, and is
        reused. Anything else is somebody's file and is never overwritten.

        **A symbolic link is not that, and the difference is the whole retention.**
        A hard link is a second *name for the inode*, so it still names the old
        database after the rename replaces the path. A symlink is a name for the
        *path*, so after the rename it resolves to the new store and the old inode
        has no name left at all — the migration would delete the very thing it
        reports having kept, and report it in the same breath. ``Path.stat``
        follows links and would say the inodes match, so the check is ``lstat``,
        and it reads the device as well: an inode number is unique only within
        one filesystem.

        Raises:
            IncompatibleStateError: If the path is occupied by anything that is
                not a hard link to the live store.
            MemoryStoreError: If the link cannot be made.
        """
        try:
            os.link(self._store, self._backup)
        except FileExistsError:
            existing = self._backup.lstat()
            live = self._store.stat()
            same_inode = (existing.st_dev, existing.st_ino) == (live.st_dev, live.st_ino)
            if not stat.S_ISLNK(existing.st_mode) and same_inode:
                return
            msg = (
                f"{self._backup} already exists and is not this store, so the "
                f"pre-migration copy has nowhere to go"
            )
            raise IncompatibleStateError(
                msg,
                expected=f"{self._backup.name} absent, or a hard link to {self._store.name}",
                found=str(self._backup),
                operator_action=f"move or delete {self._backup}, then run the migration again",
            ) from None
        except OSError as exc:
            msg = f"failed to retain the pre-migration store at {self._backup}: {exc}"
            raise MemoryStoreError(msg) from exc


def _source_columns(source: sqlite3.Connection, store: Path) -> str:
    """Which read this source supports: with its stamps, or without.

    A live store written before ADR-0219 has no ``revision`` column at all — this
    module never opens the live store through :class:`SqliteMemoryStore`, so nothing
    has migrated it — and selecting a column that is not there would fail the run
    with ``no such column`` rather than migrating it. So the shape is probed once
    per run, exactly as the store's own migrations shape-sniff through
    ``PRAGMA table_info``, and a source without the column is read with ``NULL`` in
    the stamp's place.

    Raises:
        MemoryStoreError: If the table's shape cannot be read.
    """
    try:
        names = {str(row[1]) for row in source.execute("PRAGMA table_info(records)")}
    except sqlite3.Error as exc:
        msg = f"failed to read the shape of the records table in {store}: {exc}"
        raise MemoryStoreError(msg) from exc
    return _SOURCE_COLUMNS if "revision" in names else _LEGACY_SOURCE_COLUMNS


def _issued_through(conn: sqlite3.Connection) -> int:
    """The largest revision this store's issuer has handed out, or ``0``.

    ``0`` for a store written before the issuer existed, which is the right answer
    rather than a fallback: such a store issued no stamps, so there is nothing for a
    successor's issuer to stay above.

    Raises:
        MemoryStoreError: If the issuer exists but cannot be read.
    """
    try:
        row = conn.execute("SELECT issued FROM revision_issuer WHERE singleton = 0").fetchone()
    except sqlite3.OperationalError:
        return 0
    except sqlite3.Error as exc:
        msg = f"failed to read the revision issuer: {exc}"
        raise MemoryStoreError(msg) from exc
    return 0 if row is None else int(row[0])


def _chunk(source: sqlite3.Connection, cursor: int | None, size: int, columns: str) -> list[_Row]:
    """Read the next ``size`` source rows past ``cursor``, in ``rowid`` order.

    ``cursor is None`` means nothing has been copied yet and is answered with an
    unbounded scan rather than a sentinel, because SQLite has no integer below its
    own minimum ``rowid`` (``-2**63``) to compare against. A store whose rows were
    written by this build starts at 1, but ``rowid`` is an explicit
    ``INTEGER PRIMARY KEY`` here and nothing stops a row from carrying zero or a
    negative one — and skipping such a row would present as a verification failure
    about counts rather than as anything an operator could act on.

    Raises:
        MemoryStoreError: If the store cannot be read.
    """
    where = "" if cursor is None else "WHERE rowid > ?"
    params: tuple[object, ...] = (size,) if cursor is None else (cursor, size)
    sql = f"SELECT {columns} FROM records {where} ORDER BY rowid LIMIT ?"  # noqa: S608 — module-level literals, never caller data
    try:
        return [tuple(row) for row in source.execute(sql, params)]
    except sqlite3.Error as exc:
        msg = f"failed to read a chunk of records past rowid {cursor}: {exc}"
        raise MemoryStoreError(msg) from exc


def _insert(
    work: sqlite3.Connection,
    row: _Row,
    record: MemoryRecord,
    vector: Embedding,
) -> None:
    """Write one copied row and its recomputed vector into the open transaction.

    **The stamp is carried, not recomputed** (ADR-0219 §10): a re-embedding changes
    the vectors and nothing else a caller can observe, so a record's ``revision``
    must be the same on both sides of the swap or every conditional write a caller
    was holding across the migration would be refused for a change that never
    happened. Only a source row that has *no* stamp — a store written before the
    column existed — takes one here, from the work store's own issuer.
    """
    rowid, record_id, kind, data = row[:4]
    stamp = row[_REVISION_IN_ROW]
    # ``None`` is a source with no column at all; ``0`` is a row within one that no
    # store's write path ever wrote — ADR-0219 §1 reserves that value for a record no
    # store has stored, so in both cases there is no stamp to carry and one is
    # issued. Issuing can never lose a real stamp, because ``0`` is never one.
    if stamp is None or int(stamp) == 0:
        work.execute("UPDATE revision_issuer SET issued = issued + 1 WHERE singleton = 0")
        (stamp,) = work.execute("SELECT issued FROM revision_issuer WHERE singleton = 0").fetchone()
    expires, valid_until, valid_from, about_person = _derived(record)
    work.execute(
        "INSERT INTO records"
        "(rowid, id, kind, data, expires_at, valid_until, valid_from, about_person, revision) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rowid, record_id, kind, data, expires, valid_until, valid_from, about_person, stamp),
    )
    work.execute(
        "INSERT INTO vec_records(rowid, embedding) VALUES (?, ?)",
        (rowid, sqlite_vec.serialize_float32(list(vector))),
    )


def _write_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Set one ``meta`` key inside the caller's transaction."""
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _rowids(conn: sqlite3.Connection, table: str, what: str) -> set[int]:
    """Every ``rowid`` in ``table``.

    Raises:
        MemoryStoreError: If the table cannot be scanned.
    """
    sql = f"SELECT rowid FROM {table}"  # noqa: S608 — a module-level literal, never caller data
    try:
        return {int(row[0]) for row in conn.execute(sql)}
    except sqlite3.Error as exc:
        msg = f"failed to read {table} rowids in {what}: {exc}"
        raise MemoryStoreError(msg) from exc


def _rows(conn: sqlite3.Connection, columns: str) -> Iterator[_Row]:
    """Stream every ``records`` row in ``rowid`` order, so neither store is materialised."""
    sql = f"SELECT {columns} FROM records ORDER BY rowid"  # noqa: S608 — a module-level literal, never caller data
    for row in conn.execute(sql):
        yield tuple(row)


def _fail(detail: str) -> NoReturn:
    """Refuse to swap, saying what did not line up.

    Raises:
        MemoryStoreError: Always.
    """
    msg = f"the re-embedded store does not match the live one and was not swapped in: {detail}"
    raise MemoryStoreError(msg)


def _verified_stamp(left: _Row, right: _Row) -> int:
    """Check one copied row's revision against the live store's, returning it.

    Checked here rather than left to the store, because the stamp is the one column
    a rebuild cannot re-derive from the blob (ADR-0219 §1) and so the one whose loss
    no later read would report: a swapped-in store whose rows all read back at the
    reserved ``0`` would answer every conditional write with a refusal, and one
    whose rows were re-stamped would refuse a write that is not stale.

    A source stamp of ``None`` or ``0`` is not compared, because it is not a stamp:
    the first is a store with no such column and the second is the value §1 reserves
    for a record no store has stored. :func:`_insert` issues for both, and this asks
    only that the issued value is one a store issues.

    Raises:
        MemoryStoreError: If the copied stamp is not one a store issues, or differs
            from the one the live store holds for that row.
    """
    stamp = int(right[8])
    if stamp <= 0:
        _fail(f"row {right[0]!r} carries revision {stamp}, which no store issues")
    carried = left[_REVISION_IN_ROW]
    if carried is not None and int(carried) != 0 and int(carried) != stamp:
        _fail(
            f"row {right[0]!r} was re-stamped at revision {stamp}, "
            f"where the live store holds {int(carried)}"
        )
    return stamp


def _verify_issuer(source: sqlite3.Connection, work: sqlite3.Connection, highest: int) -> None:
    """Check the built store's issuer stands above everything already issued.

    Above every stamp the store *holds*, and above every stamp the store being
    replaced ever *issued* — including the ones its deleted rows took, which is
    exactly what no surviving row records and why ADR-0219 §1 forbids rebuilding an
    issuer from the rows present.

    Raises:
        MemoryStoreError: If the issuer stands below either.
    """
    issued = _issued_through(work)
    if issued < highest:
        _fail(f"its revision issuer stands at {issued}, below the {highest} it holds")
    already = _issued_through(source)
    if issued < already:
        _fail(
            f"its revision issuer stands at {issued}, below the {already} "
            f"the live store has already issued"
        )


def _verify(
    source: sqlite3.Connection,
    work: sqlite3.Connection,
    plan: ReembedPlan,
    embedder: Embedder,
    columns: str,
) -> None:
    """Check the built store against the live one, before anything is moved (ADR-0104 §3).

    Re-reads rather than re-checking a counter, because the failures worth
    catching are the ones the writing code would not notice: a chunk lost to an
    interrupted transaction the cursor nonetheless survived, a source mutated
    between attempts, a vector row that failed to insert. A count comparison
    passes every one of them.

    The derived columns are checked against the blob beside them rather than
    against the source, because ADR-0104 §1 makes the blob authoritative and
    because the source may not carry those columns at all.

    Raises:
        MemoryStoreError: If anything does not line up. The caller has not
            touched the live store at this point and must not.
    """
    meta = _read_meta(work, str(plan.work))
    if set(meta) != _STORE_META_KEYS:
        _fail(f"its metadata holds {sorted(meta)}, expected exactly {sorted(_STORE_META_KEYS)}")
    if meta.get("embedding_model") != embedder.model_id:
        _fail(f"it is tagged {meta.get('embedding_model')!r}, expected {embedder.model_id!r}")
    if meta.get("dimensions") != str(embedder.dimensions):
        _fail(f"it is {meta.get('dimensions')}-dimensional, expected {embedder.dimensions}")

    destination = (
        "rowid, id, kind, data, expires_at, valid_until, valid_from, about_person, revision"
    )
    highest = 0
    for left, right in zip_longest(_rows(source, columns), _rows(work, destination)):
        if left is None or right is None:
            _fail("it holds a different number of records")
        if left[:4] != right[:4]:
            _fail(f"row {right[0]!r} differs from the live store's row {left[0]!r}")
        record = _decode(str(right[3]), right[1])
        if tuple(right[4:8]) != _derived(record):
            _fail(f"row {right[0]!r} has columns that disagree with the record stored in it")
        highest = max(highest, _verified_stamp(left, right))
    _verify_issuer(source, work, highest)

    record_rowids = _rowids(work, "records", str(plan.work))
    vector_rowids = _rowids(work, "vec_records", str(plan.work))
    if record_rowids != vector_rowids:
        missing = len(record_rowids - vector_rowids)
        orphaned = len(vector_rowids - record_rowids)
        _fail(f"{missing} records have no vector and {orphaned} vectors have no record")
