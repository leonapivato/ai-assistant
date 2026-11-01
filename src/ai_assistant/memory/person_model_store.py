"""A persistent :class:`~ai_assistant.core.protocols.PersonModelStore` on SQLite (ADR-0338 §10).

The person model's own store: the people the hub serves (§2:1), each one's profile of
five set fields and its append-only change log (§3:1, §3:5), the pins and style marks
that point at memories (§4:1, §5:3), and the observer's suggestions (§9:2, §9:5), on a
file of its own in the hub's data directory and outside ``MemoryStore``'s contract
(§10:1).

**Why it lives in ``memory/``.** ADR-0338 §10:1 puts it there, beside the other stores
whose contracts are their own Protocols. Nothing here imports another store, and it
holds no memory wording, no episode text and no copy of any record of another store:
only the people, the fields, the change log, and the ids of the memories and episodes
the pins, marks and suggestions point at (§10:3). Every id is held verbatim and
compared as given, since SQLite's text comparison is exact.

**The owner, from the start** (§2:1). The transaction that first creates the file's
tables also creates the one person :data:`~ai_assistant.core.types.OWNER_PERSON_ID`,
with the role ``owner``, and writes the hub's seed of their profile in that same step
(§3:7): the time zone the composition root hands over, where ``ASSISTANT_TIMEZONE`` is
set, logged as the hub's (``seed``) change; and nothing where it is not. A file that
already holds the tables is never seeded again, so the seed is written once, when the
store is first created, and a crash before that transaction commits leaves no store
behind at all. A store emptied by :meth:`SqlitePersonModelStore.clear` holds no one
afterwards, as the contract says, and is not refilled on a later open.

**The house style** of the stores beside this one: one owned connection, an
:class:`asyncio.Lock` around SQL run in a worker thread that the lock outlives
(ADR-0054), every member that writes one ``BEGIN IMMEDIATE`` transaction — which is
how §10:2's one step holds across processes as well as coroutines — and an owner-only
database file, restricted before the first write (ADR-0004 §4).

**What binds a new file under the data directory, and how each is met.**

* *Mode* (ADR-0004 §4): the file and any sidecar beside it are ``0600``.
* *Backup* (ADR-0123): the artifact carries every file in the data directory but the
  exclusions ADR-0123 §3 lists; nothing excludes this one, so it is backed up with the
  rest, and nothing is registered.
* *Purge* (ADR-0126 §1, ADR-0338 §10:5): the unit is the directory, with no per-store
  list, so deleting the owner's data destroys this file with everything else, and
  nothing is registered.
* *Upgrades* (ADR-0326, ADR-0338 §10:6): the schema is version 1, written as
  ``PRAGMA user_version`` when the tables are created. A file carrying tables under any
  other version is refused before anything is written: a later version is one this
  code does not understand (ADR-0326 §5:3), and no release wrote an earlier one. Every
  later schema change ships its upgrade from the version it replaces (§4:1).

Where the file goes, and the bound on a field's length, are the composition root's.
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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from pydantic import BaseModel, ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import PersonModelStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Person,
    PersonActHow,
    PersonModel,
    PersonModelAct,
    PersonModelExport,
    PersonModelRefusal,
    PersonModelWrite,
    PersonModelWriteKind,
    PersonRole,
    PersonSuggestion,
    Pin,
    Profile,
    ProfileChange,
    ProfileField,
    ProposedSuggestion,
    StyleMark,
    SuggestionKind,
    SuggestionState,
    describe_untrusted,
    encodable_text,
)
from ai_assistant.memory._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

__all__ = ["PERSON_MODEL_SCHEMA_VERSION", "SqlitePersonModelStore"]

_log = structlog.get_logger(__name__)

_OWNER_ONLY: Final = 0o600

#: The sidecars SQLite may keep beside a database file, each holding the same pages
#: the database does, so ADR-0004 §4 reaches them too (#490).
_SIDECARS: Final = ("-journal", "-wal", "-shm")

#: The schema this code writes and the only one it opens (ADR-0326 §5:3). No release wrote
#: an earlier version, so there is none to upgrade from yet. ``PersonModelAct``'s request
#: form (ADR-0362 §2:1-§2:2) is left out of a stored act where unset, so a file of this
#: version reads unchanged: its upgrade is the empty one ADR-0326 §4's note names, the label
#: stays, and ``tests/memory/test_person_model_store_upgrade_request_form.py`` is its test.
PERSON_MODEL_SCHEMA_VERSION: Final = 1

#: How many times a write re-mints an id that a held record already carries before it
#: fails as a store fault.
_MINT_BUDGET: Final = 8

#: The acts that may make a pin (ADR-0338 §4:1).
_PIN_ACTS: Final = frozenset({PersonActHow.PANEL, PersonActHow.APPROVAL})

_SCHEMA: Final = (
    # One row per person, in the order created. `seq` orders; `id` is the person's.
    "CREATE TABLE persons(seq INTEGER PRIMARY KEY AUTOINCREMENT, "
    "id TEXT NOT NULL UNIQUE, role TEXT NOT NULL, created_at TEXT NOT NULL)",
    # One row per field that is set; a field with no row is not set (§3:1).
    "CREATE TABLE fields(person_id TEXT NOT NULL, field TEXT NOT NULL, "
    "value TEXT NOT NULL, PRIMARY KEY(person_id, field))",
    # The change log, append-only (§3:5): written by a field's write, never changed.
    "CREATE TABLE changes(seq INTEGER PRIMARY KEY AUTOINCREMENT, person_id TEXT NOT NULL, "
    "field TEXT NOT NULL, old TEXT, new TEXT, at TEXT NOT NULL, act TEXT NOT NULL, "
    "suggestion_id TEXT)",
    "CREATE TRIGGER changes_append_only_update BEFORE UPDATE ON changes "
    "BEGIN SELECT RAISE(ABORT, 'the change log is append-only'); END",
    "CREATE TRIGGER changes_append_only_delete BEFORE DELETE ON changes "
    "WHEN (SELECT count(*) FROM persons WHERE id = OLD.person_id) > 0 "
    "BEGIN SELECT RAISE(ABORT, 'the change log is append-only'); END",
    # Pins and style marks: pointers, kept when removed (§4:7, §5:3).
    "CREATE TABLE pins(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, "
    "person_id TEXT NOT NULL, memory_id TEXT NOT NULL, pinned_at TEXT NOT NULL, "
    "act TEXT NOT NULL, removed_at TEXT)",
    "CREATE INDEX pins_by_memory ON pins(person_id, memory_id)",
    "CREATE TABLE marks(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, "
    "person_id TEXT NOT NULL, memory_id TEXT NOT NULL, marked_at TEXT NOT NULL, "
    "removed_at TEXT)",
    "CREATE INDEX marks_by_memory ON marks(person_id, memory_id)",
    # Suggestions: what each proposes, whole, as JSON in `proposed`, and the four
    # columns its equality reads (`ProposedSuggestion.equals`) beside it, written once.
    "CREATE TABLE suggestions(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, "
    "person_id TEXT NOT NULL, kind TEXT NOT NULL, field TEXT, value TEXT, memory_id TEXT, "
    "proposed TEXT NOT NULL, recorded_at TEXT NOT NULL, state TEXT NOT NULL, decided_at TEXT)",
    "CREATE INDEX suggestions_by_proposal ON suggestions(person_id, kind, field, value, memory_id)",
)

_CHANGE_COLUMNS: Final = "person_id, field, old, new, at, act, suggestion_id"
_PIN_COLUMNS: Final = "id, person_id, memory_id, pinned_at, act, removed_at"
_MARK_COLUMNS: Final = "id, person_id, memory_id, marked_at, removed_at"
_SUGGESTION_COLUMNS: Final = "id, person_id, proposed, recorded_at, state, decided_at"

_WRITTEN: Final = PersonModelWriteKind.WRITTEN
_UNCHANGED: Final = PersonModelWriteKind.UNCHANGED


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes (ADR-0054).

    Duplicated from :mod:`ai_assistant.planning.sqlite_store`, whose docstring carries
    the whole argument, rather than shared, for the reason recorded there and in
    :mod:`ai_assistant.memory.notification_outbox`: subsystems depend on ADR-0060's
    obligation and not on one way of meeting it. In short: a cancelled caller keeps
    the lock until the thread using the connection has returned, every failure the
    worker sees is relayed, and the completion wait is submitted at most once (#697).
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


def _value_fault(field: ProfileField, value: str | None, *, chars: int) -> str | None:
    """Why ``value`` is no valid value of ``field``, or ``None`` where it is (ADR-0338 §3:2).

    The contract's rule, as ``PersonModelStore.set_field`` states it, and the canonical
    fake's: ``None`` clears the field; any other value is text, not blank, within
    ``chars`` characters, with a UTF-8 encoding; and a time zone is a name ``zoneinfo``
    resolves.

    Args:
        field: The field written.
        value: The value written, or ``None`` to clear it.
        chars: The bound on a text field's length.

    Returns:
        A code-owned reason, or ``None``.
    """
    if value is None:
        return None
    if not value.strip():
        return "a field is cleared, never set to blank text"
    if len(value) > chars:
        return f"a field's value is at most {chars} characters"
    try:
        encodable_text(value)
    except ValueError:
        return "a field's value is text with a UTF-8 encoding"
    if field is ProfileField.TIME_ZONE:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError, ValueError, OSError:
            # `OSError` too: a long name reaches the file system as a path, and a name
            # it refuses there (ENAMETOOLONG) is no zone either.
            return "a time zone is a name zoneinfo resolves"
    return None


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


def _checked_instance[T](value: object, kind: type[T], *, name: str) -> T:
    """``value`` where it is a ``kind``, or a ``ValueError`` before any I/O."""
    if not isinstance(value, kind):
        msg = f"{name} must be a {kind.__name__}, got {describe_untrusted(value)}"
        raise ValueError(msg)
    return value


def _validated[M: BaseModel](value: object, kind: type[M], *, name: str) -> M:
    """``value`` as a ``kind`` whose every field passes validation, or a ``ValueError``.

    An instance is not proof of its own validity: ``model_copy(update=…)`` and
    ``model_construct`` skip validation, and a record the store committed from one would
    fail to read back, which would leave the person model unreadable (§10:5). So the
    instance's contents are validated again, nested models included, before any I/O.
    """
    held = _checked_instance(value, kind, name=name)
    try:
        return kind.model_validate(held.model_dump())
    except ValidationError as exc:
        msg = f"{name} is not a valid {kind.__name__}"
        raise ValueError(msg) from exc


def _checked_value(value: object) -> str | None:
    """A field's new value: ``None``, or a ``str``; anything else before any I/O."""
    if value is not None and not isinstance(value, str):
        msg = f"value must be a str or None, got {describe_untrusted(value)}"
        raise ValueError(msg)
    return value


def _refused(
    refusal: PersonModelRefusal, *, reason: str | None = None, record_id: str | None = None
) -> PersonModelWrite:
    return PersonModelWrite(
        kind=PersonModelWriteKind.REFUSED, refusal=refusal, reason=reason, record_id=record_id
    )


def _instant(value: datetime) -> str:
    """An instant as the file holds it: ISO 8601 text, in UTC."""
    return value.astimezone(UTC).isoformat()


def _corrupt(what: str) -> PersonModelStoreError:
    """The store fault a row that does not make its record is (§10:2's reads)."""
    return PersonModelStoreError(f"a stored {what} row is corrupt")


def _person_from(row: Sequence[Any]) -> Person:
    try:
        return Person.model_validate({"id": row[0], "role": row[1], "created_at": row[2]})
    except ValidationError as exc:
        raise _corrupt("person") from exc


def _change_from(row: Sequence[Any]) -> ProfileChange:
    try:
        return ProfileChange(
            person_id=row[0],
            field=row[1],
            old=row[2],
            new=row[3],
            at=row[4],
            act=PersonModelAct.model_validate_json(row[5]),
            suggestion_id=row[6],
        )
    except (ValidationError, TypeError) as exc:
        raise _corrupt("change-log") from exc


def _pin_from(row: Sequence[Any]) -> Pin:
    try:
        return Pin(
            id=row[0],
            person_id=row[1],
            memory_id=row[2],
            pinned_at=row[3],
            act=PersonModelAct.model_validate_json(row[4]),
            removed_at=row[5],
        )
    except (ValidationError, TypeError) as exc:
        raise _corrupt("pin") from exc


def _mark_from(row: Sequence[Any]) -> StyleMark:
    try:
        return StyleMark.model_validate(
            {
                "id": row[0],
                "person_id": row[1],
                "memory_id": row[2],
                "marked_at": row[3],
                "removed_at": row[4],
            }
        )
    except ValidationError as exc:
        raise _corrupt("style mark") from exc


def _suggestion_from(row: Sequence[Any]) -> PersonSuggestion:
    try:
        return PersonSuggestion(
            id=row[0],
            person_id=row[1],
            proposed=ProposedSuggestion.model_validate_json(row[2]),
            recorded_at=row[3],
            state=row[4],
            decided_at=row[5],
        )
    except (ValidationError, TypeError) as exc:
        raise _corrupt("suggestion") from exc


def _profile_from(rows: Sequence[Sequence[Any]]) -> Profile:
    try:
        return Profile.model_validate({ProfileField(row[0]).value: row[1] for row in rows})
    except (ValidationError, ValueError) as exc:
        raise _corrupt("field") from exc


#: What a suggestion proposes, as the four columns its equality reads: its kind, field,
#: value and memory (``ProposedSuggestion.equals``).
type _Proposal = tuple[str, str | None, str | None, str | None]


def _proposal(proposed: ProposedSuggestion) -> _Proposal:
    field = None if proposed.field is None else proposed.field.value
    return (proposed.kind.value, field, proposed.value, proposed.memory_id)


def _field_proposal(field: ProfileField, value: str) -> _Proposal:
    return (SuggestionKind.FIELD.value, field.value, value, None)


def _pin_proposal(memory_id: str) -> _Proposal:
    return (SuggestionKind.PIN.value, None, None, memory_id)


class SqlitePersonModelStore:
    """The person model, on SQLite (ADR-0338 §10), holding the owner from the start."""

    def __init__(
        self,
        *,
        path: Path | str,
        field_chars: int,
        seed_time_zone: str | None = None,
        now: Callable[[], datetime] = _utcnow,
        new_id: Callable[[str], str] = _random_id,
    ) -> None:
        """Open the store at ``path``, creating it, the owner and the seed if it is new.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
            field_chars: The bound on a text field's length (ADR-0338 §3:2), which a
                composition-root constant holds; at least 1.
            seed_time_zone: The owner's zone for the hub's seed (§3:7): the value of
                ``ASSISTANT_TIMEZONE`` where that variable is set, and ``None`` where it
                is not. Written only when the store is first created.
            now: The clock every instant the store records is read from.
            new_id: Mints a record's id from its kind (``pin``, ``mark`` or
                ``suggestion``). An id a held record already carries is minted again.

        Raises:
            ValueError: If ``field_chars`` is not an ``int`` of at least 1, or
                ``seed_time_zone`` is not a valid time zone (§3:2).
            PersonModelStoreError: If the database cannot be opened or prepared, it
                carries tables under another schema version, or the clock's reading
                for the owner's creation is not an aware instant.
        """
        if type(field_chars) is not int or field_chars < 1:
            msg = f"field_chars must be an int of at least 1, got {describe_untrusted(field_chars)}"
            raise ValueError(msg)
        if seed_time_zone is not None:
            fault = _value_fault(ProfileField.TIME_ZONE, seed_time_zone, chars=field_chars)
            if fault is not None:
                msg = f"the seed's time zone is not a valid value: {fault}"
                raise ValueError(msg)
        self._chars = field_chars
        self._seed = seed_time_zone
        # ADR-0026 §2: every reading aware and converted to UTC, checked where it is read.
        self._clock = checked_clock(now, owner="SqlitePersonModelStore")
        self._new_id = new_id
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    # --- opening -------------------------------------------------------------------

    def _setup(self) -> sqlite3.Connection:
        """Open the connection, and create the schema, the owner and the seed if new.

        Raises:
            PersonModelStoreError: If the database cannot be opened or prepared, or it
                carries tables under another schema version.
        """
        try:
            # Autocommit, so every transaction is an explicit BEGIN this module
            # controls: the driver's implicit ones are deferred, which would open a
            # read-decide-write member to the interleaving §10:2 forbids.
            conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        except (sqlite3.Error, OSError, ValueError) as exc:
            # ``ValueError`` for a path carrying a NUL, which the driver raises
            # rather than a ``sqlite3.Error`` (#1933).
            msg = f"failed to open the person-model store at {self._path!r}: {exc}"
            raise PersonModelStoreError(msg) from exc
        try:
            # Restricted before the first write: SQLite copies the file's mode onto
            # every journal it creates (ADR-0004 §4).
            self._restrict_permissions()
            with self._transaction("prepare the person-model store", conn=conn) as held:
                self._prepare(held)
        except OSError as exc:
            conn.close()  # never leak the connection when opening fails
            msg = f"failed to open the person-model store at {self._path!r}: {exc}"
            raise PersonModelStoreError(msg) from exc
        except BaseException:
            conn.close()
            raise
        return conn

    def _prepare(self, conn: sqlite3.Connection) -> None:
        """Check the file's version; create the tables, the owner and the seed if new.

        Raises:
            PersonModelStoreError: If the file carries tables under another version, or
                the clock's reading for the owner's creation is not an aware instant.
        """
        tables = conn.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        # A file is created only where it holds no table and no label. Every other label
        # is refused before anything is written, a table-free file's included: a newer
        # one is a label this code does not understand (ADR-0326 §5:3), and a file that
        # holds tables under any other version, or a label with no tables, is not one
        # any release wrote.
        if tables[0] or version != 0:
            if not tables[0] or version != PERSON_MODEL_SCHEMA_VERSION:
                msg = (
                    f"the person-model store at {self._path!r} has schema version "
                    f"{version}; this build opens only version {PERSON_MODEL_SCHEMA_VERSION}"
                )
                raise PersonModelStoreError(msg)
            return
        for statement in _SCHEMA:
            conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {PERSON_MODEL_SCHEMA_VERSION}")
        created = self._now()
        conn.execute(
            "INSERT INTO persons(id, role, created_at) VALUES (?, ?, ?)",
            (OWNER_PERSON_ID, PersonRole.OWNER.value, _instant(created)),
        )
        if self._seed is not None:
            self._insert_change(
                conn,
                ProfileChange(
                    person_id=OWNER_PERSON_ID,
                    field=ProfileField.TIME_ZONE,
                    old=None,
                    new=self._seed,
                    at=created,
                    act=PersonModelAct(how=PersonActHow.SEED),
                ),
            )
            conn.execute(
                "INSERT INTO fields(person_id, field, value) VALUES (?, ?, ?)",
                (OWNER_PERSON_ID, ProfileField.TIME_ZONE.value, self._seed),
            )
        # No value is logged: a seeded field is the owner's, and the change log holds it.
        _log.info("person_model_created", seeded=self._seed is not None)

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
        §10:2's one step.

        Raises:
            PersonModelStoreError: If the backend fails at any point.
        """
        return transaction(
            conn or self._conn, what, error=PersonModelStoreError, immediate=immediate
        )

    async def _run[T](self, fn: Callable[..., T], /, *args: object) -> T:
        """Run one member's SQL under the lock, in a worker thread the lock outlives."""
        async with self._lock:
            return await _run_to_completion(fn, *args)

    def _now(self) -> datetime:
        """One reading of the clock, taken before the write it dates changes anything.

        Raises:
            PersonModelStoreError: If the reading is not an aware instant (ADR-0026 §4).
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            msg = f"the person-model store cannot record its clock's reading: {exc}"
            raise PersonModelStoreError(msg) from exc

    def _mint(self, conn: sqlite3.Connection, kind: str) -> str:
        """A new record's id that no pin, mark or suggestion carries, removed ones included.

        Raises:
            PersonModelStoreError: If the factory kept minting a held id, or minted
                something that is not a non-blank encodable id.
        """
        for _ in range(_MINT_BUDGET):
            try:
                minted = _checked(self._new_id(kind), name="a minted id")
            except ValueError as exc:
                msg = f"the person-model store minted an id that is not one: {kind}"
                raise PersonModelStoreError(msg) from exc
            held = conn.execute(
                "SELECT 1 FROM pins WHERE id = ?1 UNION ALL SELECT 1 FROM marks WHERE id = ?1 "
                "UNION ALL SELECT 1 FROM suggestions WHERE id = ?1 LIMIT 1",
                (minted,),
            ).fetchone()
            if held is None:
                return minted
        msg = f"the person-model store minted a held {kind} id {_MINT_BUDGET} times running"
        raise PersonModelStoreError(msg)

    @staticmethod
    def _holds(conn: sqlite3.Connection, person_id: str) -> bool:
        return (
            conn.execute("SELECT 1 FROM persons WHERE id = ?", (person_id,)).fetchone() is not None
        )

    @staticmethod
    def _held_value(conn: sqlite3.Connection, person_id: str, field: ProfileField) -> str | None:
        row = conn.execute(
            "SELECT value FROM fields WHERE person_id = ? AND field = ?", (person_id, field.value)
        ).fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def _insert_change(conn: sqlite3.Connection, change: ProfileChange) -> None:
        conn.execute(
            f"INSERT INTO changes({_CHANGE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",  # noqa: S608 — only constants are interpolated
            (
                change.person_id,
                change.field.value,
                change.old,
                change.new,
                _instant(change.at),
                change.act.model_dump_json(),
                change.suggestion_id,
            ),
        )

    @staticmethod
    def _accept_equal(
        conn: sqlite3.Connection, person_id: str, at: datetime, proposal: _Proposal
    ) -> None:
        """Mark every pending suggestion equal to ``proposal`` accepted (§8:9)."""
        conn.execute(
            "UPDATE suggestions SET state = ?, decided_at = ? WHERE person_id = ? AND state = ? "
            "AND kind = ? AND field IS ? AND value IS ? AND memory_id IS ?",
            (
                SuggestionState.ACCEPTED.value,
                _instant(at),
                person_id,
                SuggestionState.PENDING.value,
                *proposal,
            ),
        )

    # --- reads ---------------------------------------------------------------------

    async def read(self, person_id: str) -> PersonModel | None:
        """Read one person's model: their profile, change log, pins, marks and suggestions.

        Raises:
            ValueError: If ``person_id`` is blank.
            PersonModelStoreError: If the store cannot be read, or a row is corrupt.
        """
        person = _checked(person_id, name="person_id")
        return await self._run(self._read_sync, person)

    def _read_sync(self, person_id: str) -> PersonModel | None:
        with self._transaction("read a person's model", immediate=False) as conn:
            row = conn.execute(
                "SELECT id, role, created_at FROM persons WHERE id = ?", (person_id,)
            ).fetchone()
            if row is None:
                return None
            where = (person_id,)
            fields = conn.execute(
                "SELECT field, value FROM fields WHERE person_id = ?", where
            ).fetchall()
            changes = conn.execute(
                f"SELECT {_CHANGE_COLUMNS} FROM changes WHERE person_id = ? ORDER BY seq",  # noqa: S608 — only constants are interpolated
                where,
            ).fetchall()
            pins = conn.execute(
                f"SELECT {_PIN_COLUMNS} FROM pins WHERE person_id = ? ORDER BY seq",  # noqa: S608 — only constants are interpolated
                where,
            ).fetchall()
            marks = conn.execute(
                f"SELECT {_MARK_COLUMNS} FROM marks WHERE person_id = ? ORDER BY seq",  # noqa: S608 — only constants are interpolated
                where,
            ).fetchall()
            pending = conn.execute(
                f"SELECT {_SUGGESTION_COLUMNS} FROM suggestions "  # noqa: S608 — only constants are interpolated
                "WHERE person_id = ? AND state = ? ORDER BY seq",
                (person_id, SuggestionState.PENDING.value),
            ).fetchall()
        return PersonModel(
            person=_person_from(row),
            profile=_profile_from(fields),
            changes=tuple(_change_from(one) for one in changes),
            pins=tuple(_pin_from(one) for one in pins),
            style_marks=tuple(_mark_from(one) for one in marks),
            suggestions=tuple(_suggestion_from(one) for one in pending),
        )

    async def export(self) -> PersonModelExport:
        """Return every record the store holds, from one consistent reading (§10:5).

        Raises:
            PersonModelStoreError: If the store cannot be read, or a row is corrupt.
        """
        return await self._run(self._export_sync)

    def _export_sync(self) -> PersonModelExport:
        with self._transaction("export the person model", immediate=False) as conn:
            persons = conn.execute(
                "SELECT id, role, created_at FROM persons ORDER BY seq"
            ).fetchall()
            fields = conn.execute("SELECT person_id, field, value FROM fields").fetchall()
            changes = conn.execute(
                f"SELECT {_CHANGE_COLUMNS} FROM changes ORDER BY seq"  # noqa: S608 — only constants are interpolated
            ).fetchall()
            pins = conn.execute(f"SELECT {_PIN_COLUMNS} FROM pins ORDER BY seq").fetchall()  # noqa: S608 — only constants are interpolated
            marks = conn.execute(f"SELECT {_MARK_COLUMNS} FROM marks ORDER BY seq").fetchall()  # noqa: S608 — only constants are interpolated
            suggestions = conn.execute(
                f"SELECT {_SUGGESTION_COLUMNS} FROM suggestions ORDER BY seq"  # noqa: S608 — only constants are interpolated
            ).fetchall()
        people = [_person_from(row) for row in persons]
        return PersonModelExport(
            persons=tuple(people),
            profiles=tuple(
                (one.id, _profile_from([row[1:] for row in fields if row[0] == one.id]))
                for one in people
            ),
            changes=tuple(_change_from(row) for row in changes),
            pins=tuple(_pin_from(row) for row in pins),
            style_marks=tuple(_mark_from(row) for row in marks),
            suggestions=tuple(_suggestion_from(row) for row in suggestions),
        )

    async def clear(self) -> int:
        """Erase every record the store holds, the owner included (§10:5).

        Returns:
            How many records went: each person and their profile, and every change-log
            entry, pin, mark and suggestion.

        Raises:
            PersonModelStoreError: If the store cannot be written.
        """
        return await self._run(self._clear_sync)

    def _clear_sync(self) -> int:
        with self._transaction("clear the person model") as conn:
            # The persons first: the change log's trigger lets a person's entries go
            # only once the person has.
            persons = conn.execute("DELETE FROM persons").rowcount
            conn.execute("DELETE FROM fields")
            erased = 2 * persons
            for table in ("changes", "pins", "marks", "suggestions"):
                erased += conn.execute(f"DELETE FROM {table}").rowcount  # noqa: S608 — only constants are interpolated
            return erased

    # --- the profile (§3) ----------------------------------------------------------

    async def set_field(
        self,
        person_id: str,
        field: ProfileField,
        value: str | None,
        *,
        act: PersonModelAct,
    ) -> PersonModelWrite:
        """Set or clear one field, logging its change in the same step (§3:2-§3:5).

        Raises:
            ValueError: If an argument is malformed.
            PersonModelStoreError: If the store cannot be read or written.
        """
        person = _checked(person_id, name="person_id")
        named = _checked_instance(field, ProfileField, name="field")
        written = _checked_value(value)
        made = _validated(act, PersonModelAct, name="act")
        return await self._run(self._set_field_sync, person, named, written, made)

    def _set_field_sync(
        self, person_id: str, field: ProfileField, value: str | None, act: PersonModelAct
    ) -> PersonModelWrite:
        with self._transaction("write a field") as conn:
            if not self._holds(conn, person_id):
                return _refused(PersonModelRefusal.UNKNOWN_PERSON)
            if act.how is PersonActHow.SUGGESTION:
                return _refused(PersonModelRefusal.INVALID_ACT)
            if (fault := _value_fault(field, value, chars=self._chars)) is not None:
                return _refused(PersonModelRefusal.INVALID_VALUE, reason=fault)
            return self._write_field(conn, person_id, field, value, act, suggestion_id=None)

    def _write_field(  # noqa: PLR0913 — one write's every part, each named for the log
        self,
        conn: sqlite3.Connection,
        person_id: str,
        field: ProfileField,
        value: str | None,
        act: PersonModelAct,
        *,
        suggestion_id: str | None,
    ) -> PersonModelWrite:
        """Write the field and its change-log entry, and accept what it takes up (§8:9)."""
        old = self._held_value(conn, person_id, field)
        at = self._now()
        if value is not None:
            self._accept_equal(conn, person_id, at, _field_proposal(field, value))
        if old == value:
            return PersonModelWrite(kind=_UNCHANGED)
        self._insert_change(
            conn,
            ProfileChange(
                person_id=person_id,
                field=field,
                old=old,
                new=value,
                at=at,
                act=act,
                suggestion_id=suggestion_id,
            ),
        )
        if value is None:
            conn.execute(
                "DELETE FROM fields WHERE person_id = ? AND field = ?", (person_id, field.value)
            )
        else:
            conn.execute(
                "INSERT INTO fields(person_id, field, value) VALUES (?, ?, ?) "
                "ON CONFLICT(person_id, field) DO UPDATE SET value = excluded.value",
                (person_id, field.value, value),
            )
        return PersonModelWrite(kind=_WRITTEN)

    # --- pins (§4) -----------------------------------------------------------------

    async def add_pin(
        self, person_id: str, memory_id: str, *, act: PersonModelAct
    ) -> PersonModelWrite:
        """Pin a memory; a standing pin on it changes nothing (§4:1-§4:2).

        Raises:
            ValueError: If an argument is malformed.
            PersonModelStoreError: If the store cannot be read or written.
        """
        person = _checked(person_id, name="person_id")
        memory = _checked(memory_id, name="memory_id")
        made = _validated(act, PersonModelAct, name="act")
        return await self._run(self._add_pin_sync, person, memory, made)

    def _add_pin_sync(
        self, person_id: str, memory_id: str, act: PersonModelAct
    ) -> PersonModelWrite:
        with self._transaction("pin a memory") as conn:
            if not self._holds(conn, person_id):
                return _refused(PersonModelRefusal.UNKNOWN_PERSON)
            if act.how not in _PIN_ACTS:
                return _refused(PersonModelRefusal.INVALID_ACT)
            return self._pin(conn, person_id, memory_id, act)

    def _pin(
        self, conn: sqlite3.Connection, person_id: str, memory_id: str, act: PersonModelAct
    ) -> PersonModelWrite:
        at = self._now()
        standing = conn.execute(
            "SELECT id FROM pins WHERE person_id = ? AND memory_id = ? AND removed_at IS NULL",
            (person_id, memory_id),
        ).fetchone()
        if standing is not None:
            self._accept_equal(conn, person_id, at, _pin_proposal(memory_id))
            return PersonModelWrite(kind=_UNCHANGED, record_id=str(standing[0]))
        # Built, and so validated, before anything is written; the transaction makes the
        # pin and the acceptance it takes up one step either way (§10:2).
        pin = Pin(
            id=self._mint(conn, "pin"),
            person_id=person_id,
            memory_id=memory_id,
            pinned_at=at,
            act=act,
        )
        conn.execute(
            f"INSERT INTO pins({_PIN_COLUMNS}) VALUES (?, ?, ?, ?, ?, NULL)",  # noqa: S608 — only constants are interpolated
            (pin.id, person_id, memory_id, _instant(at), act.model_dump_json()),
        )
        self._accept_equal(conn, person_id, at, _pin_proposal(memory_id))
        return PersonModelWrite(kind=_WRITTEN, record_id=pin.id)

    async def remove_pin(self, person_id: str, pin_id: str) -> PersonModelWrite:
        """Unpin: mark the pin removed, erasing nothing (§4:7).

        Raises:
            ValueError: If an argument is malformed.
            PersonModelStoreError: If the store cannot be read or written.
        """
        person = _checked(person_id, name="person_id")
        pin = _checked(pin_id, name="pin_id")
        return await self._run(self._remove_sync, "pins", person, pin)

    def _remove_sync(self, table: str, person_id: str, record_id: str) -> PersonModelWrite:
        """Mark a pin or a mark removed, keeping it (§4:7, §5:3)."""
        with self._transaction(f"remove from {table}") as conn:
            if not self._holds(conn, person_id):
                return _refused(PersonModelRefusal.UNKNOWN_PERSON)
            row = conn.execute(
                f"SELECT removed_at FROM {table} WHERE id = ? AND person_id = ?",  # noqa: S608 — only constants are interpolated
                (record_id, person_id),
            ).fetchone()
            if row is None:
                return _refused(PersonModelRefusal.UNKNOWN_RECORD)
            if row[0] is not None:
                return PersonModelWrite(kind=_UNCHANGED, record_id=record_id)
            conn.execute(
                f"UPDATE {table} SET removed_at = ? WHERE id = ?",  # noqa: S608 — only constants are interpolated
                (_instant(self._now()), record_id),
            )
            return PersonModelWrite(kind=_WRITTEN, record_id=record_id)

    # --- style marks (§5:3) --------------------------------------------------------

    async def add_style_mark(self, person_id: str, memory_id: str) -> PersonModelWrite:
        """Mark a memory, unless it is marked or its mark was removed (§5:3, §9:4).

        Raises:
            ValueError: If an argument is malformed.
            PersonModelStoreError: If the store cannot be read or written.
        """
        person = _checked(person_id, name="person_id")
        memory = _checked(memory_id, name="memory_id")
        return await self._run(self._add_mark_sync, person, memory)

    def _add_mark_sync(self, person_id: str, memory_id: str) -> PersonModelWrite:
        with self._transaction("mark a memory") as conn:
            if not self._holds(conn, person_id):
                return _refused(PersonModelRefusal.UNKNOWN_PERSON)
            existing = conn.execute(
                "SELECT id FROM marks WHERE person_id = ? AND memory_id = ? ORDER BY seq LIMIT 1",
                (person_id, memory_id),
            ).fetchone()
            if existing is not None:
                return PersonModelWrite(kind=_UNCHANGED, record_id=str(existing[0]))
            minted = self._mint(conn, "mark")
            conn.execute(
                f"INSERT INTO marks({_MARK_COLUMNS}) VALUES (?, ?, ?, ?, NULL)",  # noqa: S608 — only constants are interpolated
                (minted, person_id, memory_id, _instant(self._now())),
            )
            return PersonModelWrite(kind=_WRITTEN, record_id=minted)

    async def remove_style_mark(self, person_id: str, mark_id: str) -> PersonModelWrite:
        """Remove a style mark, keeping it as removed so it is never made again (§5:3).

        Raises:
            ValueError: If an argument is malformed.
            PersonModelStoreError: If the store cannot be read or written.
        """
        person = _checked(person_id, name="person_id")
        mark = _checked(mark_id, name="mark_id")
        return await self._run(self._remove_sync, "marks", person, mark)

    # --- suggestions (§9:2, §9:5) --------------------------------------------------

    async def record_suggestion(
        self, person_id: str, suggestion: ProposedSuggestion
    ) -> PersonModelWrite:
        """Record a suggestion as pending, unless held, pending or dismissed (§9:2, §9:5).

        Raises:
            ValueError: If an argument is malformed.
            PersonModelStoreError: If the store cannot be read or written.
        """
        person = _checked(person_id, name="person_id")
        proposed = _validated(suggestion, ProposedSuggestion, name="suggestion")
        return await self._run(self._record_sync, person, proposed)

    def _record_sync(self, person_id: str, proposed: ProposedSuggestion) -> PersonModelWrite:
        with self._transaction("record a suggestion") as conn:
            if not self._holds(conn, person_id):
                return _refused(PersonModelRefusal.UNKNOWN_PERSON)
            stopped = self._already_held(conn, person_id, proposed)
            if stopped is not None:
                return stopped
            equal = conn.execute(
                "SELECT id FROM suggestions WHERE person_id = ? AND state != ? AND kind = ? "
                "AND field IS ? AND value IS ? AND memory_id IS ? ORDER BY seq LIMIT 1",
                (person_id, SuggestionState.ACCEPTED.value, *_proposal(proposed)),
            ).fetchone()
            if equal is not None:
                return PersonModelWrite(kind=_UNCHANGED, record_id=str(equal[0]))
            minted = self._mint(conn, "suggestion")
            conn.execute(
                "INSERT INTO suggestions(id, person_id, kind, field, value, memory_id, proposed, "
                "recorded_at, state, decided_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    minted,
                    person_id,
                    *_proposal(proposed),
                    proposed.model_dump_json(),
                    _instant(self._now()),
                    SuggestionState.PENDING.value,
                ),
            )
            return PersonModelWrite(kind=_WRITTEN, record_id=minted)

    def _already_held(
        self, conn: sqlite3.Connection, person_id: str, proposed: ProposedSuggestion
    ) -> PersonModelWrite | None:
        """A refusal or ``unchanged`` where the profile or a pin already holds the proposal."""
        if proposed.kind is SuggestionKind.FIELD:
            field = proposed.field
            assert field is not None  # noqa: S101 — the type requires it
            fault = _value_fault(field, proposed.value, chars=self._chars)
            if fault is not None:
                return _refused(PersonModelRefusal.INVALID_VALUE, reason=fault)
            if self._held_value(conn, person_id, field) == proposed.value:
                return PersonModelWrite(kind=_UNCHANGED)
            return None
        standing = conn.execute(
            "SELECT 1 FROM pins WHERE person_id = ? AND memory_id = ? AND removed_at IS NULL",
            (person_id, proposed.memory_id),
        ).fetchone()
        return None if standing is None else PersonModelWrite(kind=_UNCHANGED)

    def _pending(
        self, conn: sqlite3.Connection, person_id: str, suggestion_id: str
    ) -> PersonSuggestion | PersonModelWrite:
        """The pending suggestion named, or the refusal deciding it would meet."""
        if not self._holds(conn, person_id):
            return _refused(PersonModelRefusal.UNKNOWN_PERSON)
        row = conn.execute(
            f"SELECT {_SUGGESTION_COLUMNS} FROM suggestions WHERE id = ? AND person_id = ?",  # noqa: S608 — only constants are interpolated
            (suggestion_id, person_id),
        ).fetchone()
        if row is None:
            return _refused(PersonModelRefusal.UNKNOWN_RECORD)
        found = _suggestion_from(row)
        if found.state is not SuggestionState.PENDING:
            return _refused(PersonModelRefusal.ALREADY_DECIDED, record_id=found.id)
        return found

    async def accept_suggestion(
        self, person_id: str, suggestion_id: str, *, by: str
    ) -> PersonModelWrite:
        """Take a suggestion's field to its value, or pin its memory, in one step.

        Raises:
            ValueError: If an argument is malformed.
            PersonModelStoreError: If the store cannot be read or written.
        """
        person = _checked(person_id, name="person_id")
        suggestion = _checked(suggestion_id, name="suggestion_id")
        accepting = _checked(by, name="by")
        return await self._run(self._accept_sync, person, suggestion, accepting)

    def _accept_sync(self, person_id: str, suggestion_id: str, by: str) -> PersonModelWrite:
        with self._transaction("accept a suggestion") as conn:
            found = self._pending(conn, person_id, suggestion_id)
            if isinstance(found, PersonModelWrite):
                return found
            proposed = found.proposed
            if proposed.kind is SuggestionKind.FIELD:
                assert proposed.field is not None  # noqa: S101 — the type requires it
                # §3:2: every write is validated, an accepted suggestion's included, against
                # the bound this store holds now, which may be tighter than the one it was
                # recorded under. A refusal leaves the suggestion pending.
                fault = _value_fault(proposed.field, proposed.value, chars=self._chars)
                if fault is not None:
                    return _refused(
                        PersonModelRefusal.INVALID_VALUE, reason=fault, record_id=found.id
                    )
                act = PersonModelAct(
                    how=PersonActHow.SUGGESTION, by=by, episode_id=proposed.episode_id
                )
                self._write_field(
                    conn, person_id, proposed.field, proposed.value, act, suggestion_id=found.id
                )
            else:
                assert proposed.memory_id is not None  # noqa: S101 — the type requires it
                panel = PersonModelAct(how=PersonActHow.PANEL, by=by)
                self._pin(conn, person_id, proposed.memory_id, panel)
            return PersonModelWrite(kind=_WRITTEN, record_id=found.id)

    async def dismiss_suggestion(self, person_id: str, suggestion_id: str) -> PersonModelWrite:
        """Dismiss a pending suggestion, so an equal one is never recorded again (§9:2).

        Raises:
            ValueError: If an argument is malformed.
            PersonModelStoreError: If the store cannot be read or written.
        """
        person = _checked(person_id, name="person_id")
        suggestion = _checked(suggestion_id, name="suggestion_id")
        return await self._run(self._dismiss_sync, person, suggestion)

    def _dismiss_sync(self, person_id: str, suggestion_id: str) -> PersonModelWrite:
        with self._transaction("dismiss a suggestion") as conn:
            found = self._pending(conn, person_id, suggestion_id)
            if isinstance(found, PersonModelWrite):
                return found
            conn.execute(
                "UPDATE suggestions SET state = ?, decided_at = ? WHERE id = ?",
                (SuggestionState.DISMISSED.value, _instant(self._now()), found.id),
            )
            return PersonModelWrite(kind=_WRITTEN, record_id=found.id)
