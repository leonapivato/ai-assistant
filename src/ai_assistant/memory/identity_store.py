"""A persistent :class:`~ai_assistant.core.protocols.IdentityStore` on SQLite (ADR-0366 §11).

The hub's identities and the accounts linked to them (§2, §3), with each link's
lowerings (§5:5), on a file of its own in the hub's data directory.

**Why it lives in ``memory/``.** Beside the other stores whose contracts are their own
Protocols, as the person-model store is: the architecture map names no subsystem for
it, and minting one is an ADR's decision. Nothing here imports another store, and it
holds no fact about a person (§2:2): only identities, the accounts tied to them, and who
lowered which link when. Every id and account identifier is held verbatim and compared
as given, since SQLite's text comparison is exact.

**The owner, from the start** (§2:5). The transaction that first creates the file's
tables also creates the one identity :data:`~ai_assistant.core.types.OWNER_PERSON_ID`.
**Every open then follows the owner's configured accounts** in that same step: each
standing ``configured`` link whose account the composition root no longer hands over is
ended, since the setting it was recorded from no longer names it, and each account handed
over that no standing link holds is tied to the owner's identity by the owner's
``configured`` act. So the owner's existing accounts are present as links when the hub
starts, without the owner doing anything (#3642), and a setting changed or cleared ends
the link it named. A link recorded from any other act is left as it is.

**The house style** of the stores beside this one: one owned connection, an
:class:`asyncio.Lock` around SQL run in a worker thread that the lock outlives
(ADR-0054), every member that writes one ``BEGIN IMMEDIATE`` transaction — which is how
the contract's one step holds across processes as well as coroutines — and an owner-only
database file, restricted before the first write (ADR-0004 §4).

**What binds a new file under the data directory, and how each is met.**

* *Mode* (ADR-0004 §4): the file and any sidecar beside it are ``0600``.
* *Backup* (ADR-0123): the artifact carries every file in the data directory but the
  exclusions ADR-0123 §3 lists; nothing excludes this one, so it is backed up with the
  rest, and nothing is registered.
* *Purge* (ADR-0126 §1): the unit is the directory, with no per-store list, so deleting
  the owner's data destroys this file with everything else, and nothing is registered.
* *Upgrades* (ADR-0326): the schema is version 1, written as ``PRAGMA user_version`` when
  the tables are created. A file carrying tables under any other version is refused
  before anything is written: a later version is one this code does not understand
  (§5:3), and no release wrote an earlier one. Every later schema change ships its
  upgrade from the version it replaces (§4:1). The upgrade check covers it (§7:3,
  ``scripts/upgrade_stores.py``).

Where the file goes, and which accounts are configured, are the composition root's.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

import structlog
from pydantic import BaseModel, ValidationError

from ai_assistant.core.channel_validation import most_sureness
from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import IdentityStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Account,
    Identity,
    IdentityExport,
    Link,
    LinkAct,
    LinkActHow,
    LinkRefusal,
    LinkWrite,
    LinkWriteKind,
    Lowering,
    Sureness,
    describe_untrusted,
    encodable_text,
)
from ai_assistant.memory._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

__all__ = ["IDENTITY_SCHEMA_VERSION", "SqliteIdentityStore"]

_log = structlog.get_logger(__name__)

_OWNER_ONLY: Final = 0o600

#: The sidecars SQLite may keep beside a database file, each holding the same pages
#: the database does, so ADR-0004 §4 reaches them too (#490).
_SIDECARS: Final = ("-journal", "-wal", "-shm")

#: The schema this code writes and the only one it opens (ADR-0326 §5:3). No release
#: wrote an earlier version, so there is none to upgrade from yet.
IDENTITY_SCHEMA_VERSION: Final = 1

#: How many times a write re-mints an id that a held record already carries before it
#: fails as a store fault.
_MINT_BUDGET: Final = 8

_SCHEMA: Final = (
    # One row per identity, in the order created. `seq` orders; `id` is the identity's.
    "CREATE TABLE identities(seq INTEGER PRIMARY KEY AUTOINCREMENT, "
    "id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)",
    # One row per link, kept when ended. A standing link ties an account, its kind and
    # identifier together, to one identity at most, which the partial unique index
    # holds; an ended one ties nothing. `act` is the `LinkAct` as JSON.
    "CREATE TABLE links(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, "
    "person_id TEXT NOT NULL, kind TEXT NOT NULL, account TEXT NOT NULL, "
    "act TEXT NOT NULL, made_at TEXT NOT NULL, ended_at TEXT)",
    "CREATE UNIQUE INDEX links_standing ON links(kind, account) WHERE ended_at IS NULL",
    "CREATE INDEX links_by_person ON links(person_id)",
    # One row per lowering, kept when withdrawn (§5:5).
    "CREATE TABLE lowerings(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, "
    "link_id TEXT NOT NULL, level TEXT NOT NULL, made_by TEXT NOT NULL, "
    "made_at TEXT NOT NULL, withdrawn_at TEXT)",
    "CREATE INDEX lowerings_by_link ON lowerings(link_id)",
)

_LINK_COLUMNS: Final = "id, person_id, kind, account, act, made_at, ended_at"
_LOWERING_COLUMNS: Final = "id, link_id, level, made_by, made_at, withdrawn_at"

#: The act every configured account is linked by: the owner's own configuration.
_CONFIGURED: Final = LinkAct(how=LinkActHow.CONFIGURED, by=OWNER_PERSON_ID)


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes (ADR-0054).

    Duplicated from :mod:`ai_assistant.memory.person_model_store`, whose docstring
    points at the whole argument, rather than shared: subsystems depend on ADR-0060's
    obligation and not on one way of meeting it. In short: a cancelled caller keeps the
    lock until the thread using the connection has returned, every failure the worker
    sees is relayed, and the completion wait is submitted at most once (#697).
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


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _random_id(kind: str) -> str:
    """A fresh record id of ``kind``: the kind, then 128 random bits as lowercase hex."""
    return f"{kind}:{uuid4().hex}"


def _checked(value: object, *, name: str) -> str:
    """A non-blank ``str`` with a UTF-8 encoding, or a ``ValueError`` before any I/O."""
    if not isinstance(value, str) or not value.strip():
        msg = f"{name} must be a non-blank str, got {describe_untrusted(value)}"
        raise ValueError(msg)
    try:
        return encodable_text(value)
    except ValueError as exc:
        msg = f"{name} must be text with a UTF-8 encoding"
        raise ValueError(msg) from exc


def _validated[M: BaseModel](value: object, kind: type[M], *, name: str) -> M:
    """``value`` as a ``kind`` whose every field passes validation, or a ``ValueError``.

    An instance is not proof of its own validity: ``model_copy(update=…)`` and
    ``model_construct`` skip validation, and a record the store committed from one would
    fail to read back. So the instance's contents are validated again before any I/O.
    """
    if not isinstance(value, kind):
        msg = f"{name} must be a {kind.__name__}, got {describe_untrusted(value)}"
        raise ValueError(msg)
    try:
        return kind.model_validate(value.model_dump())
    except ValidationError as exc:
        msg = f"{name} is not a valid {kind.__name__}"
        raise ValueError(msg) from exc


def _level(value: object) -> Sureness:
    """``value`` where it is a level, or a ``ValueError`` before any I/O."""
    if not isinstance(value, Sureness):
        msg = f"level must be a Sureness, got {describe_untrusted(value)}"
        raise ValueError(msg)
    return value


def _refused(refusal: LinkRefusal) -> LinkWrite:
    return LinkWrite(kind=LinkWriteKind.REFUSED, refusal=refusal)


def _instant(value: datetime) -> str:
    """An instant as the file holds it: ISO 8601 text, in UTC."""
    return value.astimezone(UTC).isoformat()


def _corrupt(what: str) -> IdentityStoreError:
    """The store fault a row that does not make its record is."""
    return IdentityStoreError(f"a stored {what} row is corrupt")


def _lowering_from(row: Sequence[Any]) -> Lowering:
    try:
        return Lowering.model_validate(
            {
                "id": row[0],
                "level": row[2],
                "by": row[3],
                "made_at": row[4],
                "withdrawn_at": row[5],
            }
        )
    except ValidationError as exc:
        raise _corrupt("lowering") from exc


def _link_from(row: Sequence[Any], lowerings: Sequence[Sequence[Any]]) -> Link:
    """A link from its row and its lowerings' rows, in the order made."""
    made = tuple(_lowering_from(one) for one in lowerings if one[1] == row[0])
    try:
        return Link(
            id=row[0],
            person_id=row[1],
            account=Account(kind=row[2], identifier=row[3]),
            act=LinkAct.model_validate_json(row[4]),
            made_at=row[5],
            lowerings=made,
            ended_at=row[6],
        )
    except (ValidationError, TypeError) as exc:
        raise _corrupt("link") from exc


def _identity_from(row: Sequence[Any], links: Sequence[Link]) -> Identity:
    try:
        return Identity.model_validate(
            {
                "id": row[0],
                "created_at": row[1],
                "links": [one for one in links if one.person_id == row[0]],
            }
        )
    except ValidationError as exc:
        raise _corrupt("identity") from exc


class SqliteIdentityStore:
    """The hub's identities and links, on SQLite (ADR-0366 §2, §3, §5:5)."""

    def __init__(
        self,
        *,
        path: Path | str,
        configured: Sequence[Account] | None = None,
        now: Callable[[], datetime] = _utcnow,
        new_id: Callable[[str], str] = _random_id,
    ) -> None:
        """Open the store at ``path``: create it and the owner if new, and link the configured.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
            configured: The accounts the owner's configuration names, followed in the
                step that opens the store: each standing ``configured`` link whose account
                it does not name is ended, and each account it names that no standing
                link holds is linked to the owner's identity by a ``configured`` act of
                the owner's, in the order given. ``None``, for an opening that is not the
                hub's start, such as a tool reading the file, follows nothing and leaves
                every link as it is; only the composition root hands the configuration.
            now: The clock every instant the store records is read from.
            new_id: Mints a record's id from its kind (``link`` or ``lowering``). An id
                a held record already carries is minted again.

        Raises:
            ValueError: If an entry of ``configured`` is not a valid ``Account``.
            IdentityStoreError: If the database cannot be opened or prepared, it carries
                tables under another schema version, or the clock's reading is not an
                aware instant.
        """
        self._configured = (
            None
            if configured is None
            else tuple(_validated(one, Account, name="a configured account") for one in configured)
        )
        # ADR-0026 §2: every reading aware and converted to UTC, checked where it is read.
        self._clock = checked_clock(now, owner="SqliteIdentityStore")
        self._new_id = new_id
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    # --- opening -------------------------------------------------------------------

    def _setup(self) -> sqlite3.Connection:
        """Open the connection; create the schema and the owner if new; link the configured.

        Raises:
            IdentityStoreError: If the database cannot be opened or prepared, or it
                carries tables under another schema version.
        """
        try:
            # Autocommit, so every transaction is an explicit BEGIN this module
            # controls: the driver's implicit ones are deferred, which would open a
            # read-decide-write member to interleaving.
            conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        except (sqlite3.Error, OSError, ValueError) as exc:
            # ``ValueError`` for a path carrying a NUL, which the driver raises
            # rather than a ``sqlite3.Error`` (#1933).
            msg = f"failed to open the identity store at {self._path!r}: {exc}"
            raise IdentityStoreError(msg) from exc
        try:
            try:
                # Restricted before the first write: SQLite copies the file's mode onto
                # every journal it creates (ADR-0004 §4).
                self._restrict_permissions()
            except OSError as exc:
                msg = f"failed to open the identity store at {self._path!r}: {exc}"
                raise IdentityStoreError(msg) from exc
            # Outside the file's own translation: an exception the injected clock raises
            # itself propagates unwrapped (ADR-0026 §2), after the step rolls back.
            with self._transaction("prepare the identity store", conn=conn) as held:
                self._prepare(held)
                self._follow_configured(held)
        except BaseException:
            conn.close()  # never leak the connection when opening fails
            raise
        return conn

    def _prepare(self, conn: sqlite3.Connection) -> None:
        """Check the file's version; create the tables and the owner if new.

        Raises:
            IdentityStoreError: If the file carries tables under another version, or the
                clock's reading for the owner's creation is not an aware instant.
        """
        tables = conn.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        # A file is created only where it holds no table and no label. Every other label
        # is refused before anything is written, a table-free file's included: a newer
        # one is a label this code does not understand (ADR-0326 §5:3), and a file that
        # holds tables under any other version, or a label with no tables, is not one
        # any release wrote.
        if tables[0] or version != 0:
            if not tables[0] or version != IDENTITY_SCHEMA_VERSION:
                msg = (
                    f"the identity store at {self._path!r} has schema version {version}; "
                    f"this build opens only version {IDENTITY_SCHEMA_VERSION}"
                )
                raise IdentityStoreError(msg)
            return
        for statement in _SCHEMA:
            conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {IDENTITY_SCHEMA_VERSION}")
        conn.execute(
            "INSERT INTO identities(id, created_at) VALUES (?, ?)",
            (OWNER_PERSON_ID, _instant(self._now())),
        )
        _log.info("identity_store_created")

    def _follow_configured(self, conn: sqlite3.Connection) -> None:
        """End the configured links no longer configured; link the accounts newly so.

        #3642's "already linked", followed at every open: a standing ``configured`` link
        whose account the configuration no longer names is ended, and each configured
        account no standing link holds is tied to the owner's identity. Where the
        owner's identity is not held, as no release leaves a file, nothing is linked: a
        link ties an account to an identity the store holds. With no configuration handed
        over, nothing is followed.
        """
        configured = self._configured
        if configured is None:
            return
        at: datetime | None = None
        standing = conn.execute(
            "SELECT id, kind, account, act FROM links WHERE ended_at IS NULL ORDER BY seq"
        ).fetchall()
        ended: list[str] = []
        for row in standing:
            try:
                act = LinkAct.model_validate_json(row[3])
                account = Account(kind=row[1], identifier=row[2])
            except (ValidationError, TypeError) as exc:
                raise _corrupt("link") from exc
            if act.how is LinkActHow.CONFIGURED and account not in configured:
                ended.append(row[0])
        if ended:
            at = self._now()
            conn.executemany(
                "UPDATE links SET ended_at = ? WHERE id = ?",
                [(_instant(at), one) for one in ended],
            )
        linked = 0
        if self._holds(conn, OWNER_PERSON_ID):
            for account in configured:
                if self._held_link_row(conn, account) is not None:
                    continue
                at = at or self._now()
                self._insert_link(conn, OWNER_PERSON_ID, account, _CONFIGURED, at)
                linked += 1
        if linked or ended:
            # No account is logged: which accounts the owner has is the owner's.
            _log.info("identity_store_followed_configured", linked=linked, ended=len(ended))

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case, and a *symlink* under a sidecar's
        name is skipped rather than followed, since ``chmod`` follows links.
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

    # --- internals -----------------------------------------------------------------

    def _transaction(
        self, what: str, *, immediate: bool = True, conn: sqlite3.Connection | None = None
    ) -> AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front, so the read each write decides on
        cannot be interleaved by another writer, in this process or another: that is
        the contract's one step.

        Raises:
            IdentityStoreError: If the backend fails at any point.
        """
        return transaction(conn or self._conn, what, error=IdentityStoreError, immediate=immediate)

    async def _run[T](self, fn: Callable[..., T], /, *args: object) -> T:
        """Run one member's SQL under the lock, in a worker thread the lock outlives."""
        async with self._lock:
            return await _run_to_completion(fn, *args)

    def _now(self) -> datetime:
        """One reading of the clock, taken before the write it dates changes anything.

        Raises:
            IdentityStoreError: If the reading is not an aware instant (ADR-0026 §4).
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            msg = f"the identity store cannot record its clock's reading: {exc}"
            raise IdentityStoreError(msg) from exc

    def _mint(self, conn: sqlite3.Connection, kind: str) -> str:
        """A new record's id that no link or lowering carries, withdrawn ones included.

        Raises:
            IdentityStoreError: If the factory kept minting a held id, or minted
                something that is not a non-blank encodable id.
        """
        for _ in range(_MINT_BUDGET):
            try:
                minted = _checked(self._new_id(kind), name="a minted id")
            except ValueError as exc:
                msg = f"the identity store minted an id that is not one: {kind}"
                raise IdentityStoreError(msg) from exc
            held = conn.execute(
                "SELECT 1 FROM links WHERE id = ?1 UNION ALL "
                "SELECT 1 FROM lowerings WHERE id = ?1 LIMIT 1",
                (minted,),
            ).fetchone()
            if held is None:
                return minted
        msg = f"the identity store minted a held {kind} id {_MINT_BUDGET} times running"
        raise IdentityStoreError(msg)

    @staticmethod
    def _holds(conn: sqlite3.Connection, person_id: str) -> bool:
        row = conn.execute("SELECT 1 FROM identities WHERE id = ?", (person_id,)).fetchone()
        return row is not None

    @staticmethod
    def _held_link_row(conn: sqlite3.Connection, account: Account) -> Sequence[Any] | None:
        row: Sequence[Any] | None = conn.execute(
            f"SELECT {_LINK_COLUMNS} FROM links "  # noqa: S608 — only constants are interpolated
            "WHERE kind = ? AND account = ? AND ended_at IS NULL",
            (account.kind, account.identifier),
        ).fetchone()
        return row

    def _insert_link(
        self, conn: sqlite3.Connection, person_id: str, account: Account, act: LinkAct, at: datetime
    ) -> str:
        link_id = self._mint(conn, "link")
        conn.execute(
            "INSERT INTO links(id, person_id, kind, account, act, made_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                link_id,
                person_id,
                account.kind,
                account.identifier,
                act.model_dump_json(),
                _instant(at),
            ),
        )
        return link_id

    @staticmethod
    def _lowerings_where(conn: sqlite3.Connection, where: str, value: str) -> list[Any]:
        """Every lowering of the links ``where`` selects, in the order made.

        A subquery rather than one bound parameter per link, so a person's link history,
        ended links included, is read whole however long it grows.
        """
        rows: list[Any] = conn.execute(
            f"SELECT {_LOWERING_COLUMNS} FROM lowerings "  # noqa: S608 — only constants are interpolated
            f"WHERE link_id IN (SELECT id FROM links WHERE {where} = ?) ORDER BY seq",
            (value,),
        ).fetchall()
        return rows

    # --- reads ---------------------------------------------------------------------

    async def identity(self, person_id: str) -> Identity | None:
        """Read one identity, with every link and every lowering of each.

        Raises:
            ValueError: If ``person_id`` is not a non-blank ``str``.
            IdentityStoreError: If the store cannot be read, or a row is corrupt.
        """
        person = _checked(person_id, name="person_id")
        return await self._run(self._identity_sync, person)

    def _identity_sync(self, person_id: str) -> Identity | None:
        with self._transaction("read an identity", immediate=False) as conn:
            row = conn.execute(
                "SELECT id, created_at FROM identities WHERE id = ?", (person_id,)
            ).fetchone()
            if row is None:
                return None
            links = conn.execute(
                f"SELECT {_LINK_COLUMNS} FROM links WHERE person_id = ? ORDER BY seq",  # noqa: S608 — only constants are interpolated
                (person_id,),
            ).fetchall()
            lowerings = self._lowerings_where(conn, "person_id", person_id)
        return _identity_from(row, [_link_from(one, lowerings) for one in links])

    async def find_link(self, account: Account) -> Link | None:
        """Find the link ``account`` is tied to, where one is.

        Raises:
            ValueError: If ``account`` is not a valid ``Account``.
            IdentityStoreError: If the store cannot be read, or a row is corrupt.
        """
        checked = _validated(account, Account, name="account")
        return await self._run(self._find_link_sync, checked)

    def _find_link_sync(self, account: Account) -> Link | None:
        with self._transaction("find a link", immediate=False) as conn:
            row = self._held_link_row(conn, account)
            if row is None:
                return None
            # A link whose identity is not held is no record any write made: never an
            # identification (§4:1), and the export refuses it as corrupt too.
            if not self._holds(conn, row[1]):
                raise _corrupt("link")
            lowerings = self._lowerings_where(conn, "id", row[0])
        return _link_from(row, lowerings)

    async def export(self) -> IdentityExport:
        """Return every record the store holds, from one consistent reading.

        Raises:
            IdentityStoreError: If the store cannot be read, or a row is corrupt.
        """
        return await self._run(self._export_sync)

    def _export_sync(self) -> IdentityExport:
        with self._transaction("export the identities", immediate=False) as conn:
            identities = conn.execute(
                "SELECT id, created_at FROM identities ORDER BY seq"
            ).fetchall()
            links = conn.execute(f"SELECT {_LINK_COLUMNS} FROM links ORDER BY seq").fetchall()  # noqa: S608 — only constants are interpolated
            lowerings = conn.execute(
                f"SELECT {_LOWERING_COLUMNS} FROM lowerings ORDER BY seq"  # noqa: S608 — only constants are interpolated
            ).fetchall()
        held = [_link_from(one, lowerings) for one in links]
        # A link or a lowering whose holder is not held is no record any write made, and
        # an export that left it out would not carry every record the file holds.
        known = {row[0] for row in identities}
        if any(one.person_id not in known for one in held):
            raise _corrupt("link")
        linked = {one.id for one in held}
        if any(row[1] not in linked for row in lowerings):
            raise _corrupt("lowering")
        return IdentityExport(identities=tuple(_identity_from(row, held) for row in identities))

    # --- writes --------------------------------------------------------------------

    async def link(self, person_id: str, account: Account, *, act: LinkAct) -> LinkWrite:
        """Tie ``account`` to ``person_id``'s identity by ``act``, in one step.

        Raises:
            ValueError: If an argument is malformed.
            IdentityStoreError: If the store cannot be read or written.
        """
        person = _checked(person_id, name="person_id")
        checked = _validated(account, Account, name="account")
        made = _validated(act, LinkAct, name="act")
        return await self._run(self._link_sync, person, checked, made)

    def _link_sync(self, person_id: str, account: Account, act: LinkAct) -> LinkWrite:
        with self._transaction("make a link") as conn:
            if not self._holds(conn, person_id) or not self._holds(conn, act.by):
                return _refused(LinkRefusal.UNKNOWN_PERSON)
            row = self._held_link_row(conn, account)
            if row is not None:
                if row[1] != person_id:
                    return _refused(LinkRefusal.ALREADY_LINKED)
                return LinkWrite(kind=LinkWriteKind.UNCHANGED, record_id=row[0])
            at = self._now()
            link_id = self._insert_link(conn, person_id, account, act, at)
        return LinkWrite(kind=LinkWriteKind.WRITTEN, record_id=link_id)

    async def lower(self, link_id: str, level: Sureness, *, by: str) -> LinkWrite:
        """Lower a link's level, by the owner or the person it identifies, in one step.

        Raises:
            ValueError: If an argument is malformed.
            IdentityStoreError: If the store cannot be read or written.
        """
        held = _checked(link_id, name="link_id")
        lowered = _level(level)
        maker = _checked(by, name="by")
        return await self._run(self._lower_sync, held, lowered, maker)

    def _lower_sync(self, link_id: str, level: Sureness, by: str) -> LinkWrite:
        with self._transaction("lower a link") as conn:
            row = conn.execute(
                "SELECT person_id, kind FROM links WHERE id = ? AND ended_at IS NULL", (link_id,)
            ).fetchone()
            if row is None:
                return _refused(LinkRefusal.UNKNOWN_RECORD)
            if not self._holds(conn, by):
                return _refused(LinkRefusal.UNKNOWN_PERSON)
            if by not in {OWNER_PERSON_ID, row[0]}:
                return _refused(LinkRefusal.NOT_ALLOWED)
            same = conn.execute(
                "SELECT id FROM lowerings WHERE link_id = ? AND made_by = ? AND level = ? "
                "AND withdrawn_at IS NULL ORDER BY seq LIMIT 1",
                (link_id, by, level.value),
            ).fetchone()
            if same is not None:
                return LinkWrite(kind=LinkWriteKind.UNCHANGED, record_id=same[0])
            if level >= most_sureness(row[1]):
                return _refused(LinkRefusal.NOT_A_LOWERING)
            at = self._now()
            lowering_id = self._mint(conn, "lowering")
            conn.execute(
                "INSERT INTO lowerings(id, link_id, level, made_by, made_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (lowering_id, link_id, level.value, by, _instant(at)),
            )
        return LinkWrite(kind=LinkWriteKind.WRITTEN, record_id=lowering_id)

    async def end_link(self, link_id: str) -> LinkWrite:
        """End a link whose act no longer stands, keeping it, in one step.

        Raises:
            ValueError: If ``link_id`` is not a non-blank ``str``.
            IdentityStoreError: If the store cannot be read or written.
        """
        held = _checked(link_id, name="link_id")
        return await self._run(self._end_sync, held)

    def _end_sync(self, link_id: str) -> LinkWrite:
        with self._transaction("end a link") as conn:
            row = conn.execute("SELECT ended_at FROM links WHERE id = ?", (link_id,)).fetchone()
            if row is None:
                return _refused(LinkRefusal.UNKNOWN_RECORD)
            if row[0] is not None:
                return LinkWrite(kind=LinkWriteKind.UNCHANGED, record_id=link_id)
            conn.execute(
                "UPDATE links SET ended_at = ? WHERE id = ?", (_instant(self._now()), link_id)
            )
        return LinkWrite(kind=LinkWriteKind.WRITTEN, record_id=link_id)

    async def withdraw_lowering(self, lowering_id: str, *, by: str) -> LinkWrite:
        """Withdraw a lowering, by its maker alone, in one step.

        Raises:
            ValueError: If an argument is malformed.
            IdentityStoreError: If the store cannot be read or written.
        """
        held = _checked(lowering_id, name="lowering_id")
        maker = _checked(by, name="by")
        return await self._run(self._withdraw_sync, held, maker)

    def _withdraw_sync(self, lowering_id: str, by: str) -> LinkWrite:
        with self._transaction("withdraw a lowering") as conn:
            row = conn.execute(
                "SELECT made_by, withdrawn_at FROM lowerings WHERE id = ?", (lowering_id,)
            ).fetchone()
            if row is None:
                return _refused(LinkRefusal.UNKNOWN_RECORD)
            if not self._holds(conn, by):
                return _refused(LinkRefusal.UNKNOWN_PERSON)
            if row[0] != by:
                return _refused(LinkRefusal.NOT_ALLOWED)
            if row[1] is not None:
                return LinkWrite(kind=LinkWriteKind.UNCHANGED, record_id=lowering_id)
            conn.execute(
                "UPDATE lowerings SET withdrawn_at = ? WHERE id = ?",
                (_instant(self._now()), lowering_id),
            )
        return LinkWrite(kind=LinkWriteKind.WRITTEN, record_id=lowering_id)
