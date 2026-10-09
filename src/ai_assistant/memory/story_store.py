"""A persistent :class:`~ai_assistant.core.protocols.StoryStore` on SQLite (ADR-0289 §1).

The story store holds which experiences belong to the same matter: stories, their
members, and an append-only log of every change, on its own file, ``stories.db``,
in the data directory. Beside each story it keeps the story's page (ADR-0300 §3,
ADR-0303 §§2-4): its notes, its current page, and the page's append-only version log.

**Why this module lives in ``memory/`` while its contract does not.** ADR-0289 §1
puts the store in ``memory/`` and makes ``StoryStore`` its own Protocol, not a
corner of ``MemoryStore``: the store is a graph with its own log, and it reads no
other store. Nothing here imports the memory store, and nothing in the memory store
imports this — the placement ``deferral_store.py`` already has, for the same reason.

**Two records, one transaction.** The clean view (``members``) and the change log
(``log``) are written in one ``BEGIN IMMEDIATE`` transaction per operation, so
either both change or neither does. A refusal discovered only after the writes —
a merge that would close a loop — raises inside the transaction, which rolls back
everything the operation wrote, the log's sequence counter included. The log is
append-only by trigger as well as by code: an ``UPDATE`` or ``DELETE`` on it aborts.

**Positions are log sequence numbers.** An entry's place in link order is the
sequence number of the ``added`` line that put it there, which is unique across the
store and ascending, so a page of the view resumes after a position and a merge that
keeps an existing entry keeps its place by keeping its row.

**The page's records, and one counter for them.** A note's identity, a version's,
and the moment a note or an activation member became pending on a story are all
drawn from one counter (``ticks``), so they are comparable: a page read reports the
counter as its ``as_of``, and a page write built on that read refuses where a
version newer than it exists and takes in only what was pending at it (ADR-0300
§3:8). Pending is a column, ``pending_since``, on the note and on the member row:
set when the note or the member comes to a story, cleared when a version takes it
in. A note's own fields cannot be rewritten nor the note removed, by trigger; only
which story holds it and whether it is pending there change. The version log is
append-only by trigger, and the current page is the one record of the page kept as
text, its lines and its mark, replaced whole by each write under ``secure_delete``,
so the replaced page's text is overwritten rather than left in a freed page of the
file. No rule here reads the activation a note was written during (ADR-0303 §2:4):
a split and a move carry exactly the notes they name (§6).

**A decision on a flag is a log line** (ADR-0302 §3). A ``decided`` line carries the
flag it answers, as canonical JSON text of its identity in ``answers``, and the
outcome in ``outcome``; it is written in the same transaction as the change it
records, after that change's lines, so the two stand or fall together. The checks a
write answering a flag makes — that the flag is one the version log or the change
log holds, and that no ``decided`` line answers it yet — are made inside that
transaction, so two writers cannot both answer one flag. A tidy-up's flags are the
only ones (ADR-0303 §8): a flag named by an activation is never held.

The file is created owner-only (ADR-0004 §4). The membership records hold
identities and instants only (ADR-0289 §2:7); the notes and the current page hold
the text ADR-0300 §3 gives them, which is a fact about the owner's life as well.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import StoryStoreError
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    STORY_ID_PREFIX,
    STORY_PAGE_CAP_CHARS,
    Identifier,
    StoryActor,
    StoryChange,
    StoryCurrentPage,
    StoryDecision,
    StoryEntry,
    StoryFlagName,
    StoryHeader,
    StoryLogLine,
    StoryLogPage,
    StoryMember,
    StoryMemberKind,
    StoryNote,
    StoryNoteAuthor,
    StoryNoteId,
    StoryNoteList,
    StoryNoteOutcome,
    StoryOutcome,
    StoryPage,
    StoryPageDraft,
    StoryPageOutcome,
    StoryPageRefusal,
    StoryPageRefusalReason,
    StoryPageState,
    StoryPageVersion,
    StoryPageVersionList,
    StoryRefusal,
    StoryRefusalReason,
    StoryViewPage,
    check_story_as_of,
    check_story_page,
    describe_untrusted,
    story_members,
    story_note_ids,
)
from ai_assistant.memory._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

    from ai_assistant.core.clock import Clock

_OWNER_ONLY = 0o600

#: The sidecars SQLite may keep beside a database file; each holds the database's
#: pages, so ADR-0004 §4 reaches them too (#490).
_SIDECARS = ("-journal", "-wal", "-shm")

#: The schema this module writes, held in ``PRAGMA user_version``. A file carrying
#: another version is refused at open rather than read under the wrong layout, except
#: version 1, ADR-0289's layout, version 2, ADR-0300's, and version 3, ADR-0302's,
#: which are migrated in place (see :data:`_MIGRATE_1`, :data:`_MIGRATE_2` and
#: :func:`_migrate_3`).
_SCHEMA_VERSION: Final = 4

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_IDENTIFIER: TypeAdapter[str] = TypeAdapter(Identifier)

_SCHEMA: Final = (
    "CREATE TABLE IF NOT EXISTS stories("
    "id TEXT PRIMARY KEY, created_seq INTEGER NOT NULL UNIQUE, "
    "created_at INTEGER NOT NULL, merged_into TEXT)",
    "CREATE TABLE IF NOT EXISTS members("
    "story_id TEXT NOT NULL, kind TEXT NOT NULL, member_id TEXT NOT NULL, "
    "position INTEGER NOT NULL UNIQUE, linked_at INTEGER NOT NULL, actor TEXT NOT NULL, "
    "pending_since INTEGER, "
    "PRIMARY KEY(story_id, kind, member_id))",
    "CREATE INDEX IF NOT EXISTS members_order ON members(story_id, position)",
    "CREATE INDEX IF NOT EXISTS members_reverse ON members(kind, member_id)",
    "CREATE TABLE IF NOT EXISTS log("
    "sequence INTEGER PRIMARY KEY AUTOINCREMENT, story_id TEXT NOT NULL, "
    "change TEXT NOT NULL, member_kind TEXT, member_id TEXT, other_story TEXT, "
    "actor TEXT NOT NULL, trigger_id TEXT, at INTEGER NOT NULL, "
    "answers TEXT, outcome TEXT)",
    "CREATE INDEX IF NOT EXISTS log_story ON log(story_id, sequence)",
    # What a write answering a flag checks (ADR-0302 §4): a ``decided`` line answering
    # the flag.
    "CREATE INDEX IF NOT EXISTS log_answers ON log(answers) WHERE answers IS NOT NULL",
    "CREATE TRIGGER IF NOT EXISTS log_never_rewritten BEFORE UPDATE ON log "
    "BEGIN SELECT RAISE(ABORT, 'the story change log is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS log_never_removed BEFORE DELETE ON log "
    "BEGIN SELECT RAISE(ABORT, 'the story change log is append-only'); END",
    # --- the page (ADR-0300 §3) ---
    "CREATE TABLE IF NOT EXISTS ticks(only INTEGER PRIMARY KEY CHECK (only = 0), "
    "value INTEGER NOT NULL)",
    "INSERT OR IGNORE INTO ticks(only, value) VALUES(0, 0)",
    "CREATE TABLE IF NOT EXISTS notes("
    "id INTEGER PRIMARY KEY, story_id TEXT NOT NULL, text TEXT NOT NULL, "
    "author TEXT NOT NULL, written_during TEXT, outside INTEGER NOT NULL, "
    "written_at INTEGER NOT NULL, pending_since INTEGER)",
    "CREATE INDEX IF NOT EXISTS notes_story ON notes(story_id, id)",
    "CREATE TRIGGER IF NOT EXISTS notes_never_rewritten "
    "BEFORE UPDATE OF id, text, author, written_during, outside, written_at ON notes "
    "BEGIN SELECT RAISE(ABORT, 'a story note is never rewritten'); END",
    "CREATE TRIGGER IF NOT EXISTS notes_never_removed BEFORE DELETE ON notes "
    "BEGIN SELECT RAISE(ABORT, 'a story note is never removed'); END",
    "CREATE TABLE IF NOT EXISTS pages("
    "story_id TEXT PRIMARY KEY, version INTEGER NOT NULL, written_at INTEGER NOT NULL, "
    "lines TEXT NOT NULL, outside INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS versions("
    "version INTEGER PRIMARY KEY, story_id TEXT NOT NULL, written_at INTEGER NOT NULL, "
    "record TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS versions_story ON versions(story_id, version)",
    "CREATE TRIGGER IF NOT EXISTS versions_never_rewritten BEFORE UPDATE ON versions "
    "BEGIN SELECT RAISE(ABORT, 'the page version log is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS versions_never_removed BEFORE DELETE ON versions "
    "BEGIN SELECT RAISE(ABORT, 'the page version log is append-only'); END",
)

#: ADR-0289's layout, version 1, to this one. The member rows gain ``pending_since``,
#: and every activation member is pending at the counter's start: no version of any
#: page has been written, so none has taken one in (ADR-0300 §3:8). The page's tables
#: are then created by :data:`_SCHEMA` like any other missing table.
_MIGRATE_1: Final = (
    "ALTER TABLE members ADD COLUMN pending_since INTEGER",
    "UPDATE members SET pending_since = 0 WHERE kind = 'activation'",
)

#: ADR-0300's layout, version 2, to this one (ADR-0302 §10). The log gains what a
#: ``decided`` line carries; every line written before it carries neither, as no
#: line but a ``decided`` one does, so none is rewritten — which the log's own
#: triggers would refuse in any case. The indexes are then created by
#: :data:`_SCHEMA`.
_MIGRATE_2: Final = (
    "ALTER TABLE log ADD COLUMN answers TEXT",
    "ALTER TABLE log ADD COLUMN outcome TEXT",
)

#: ADR-0302's layout, version 3, to this one (ADR-0303 §4:8), and ADR-0300's, version 2,
#: once :data:`_MIGRATE_2` has run: the statements that need no record read, which
#: :func:`_migrate_3` runs before it rewrites the records. A
#: note's resting activation becomes the activation it was written during, under a
#: column renamed in place (SQLite renames it in the trigger guarding it as well); the
#: index a move found notes by goes, as does the one understanding's flags were found
#: by; and the current page gains its mark. The version log's trigger is dropped for
#: the rewrite alone, and :data:`_SCHEMA` creates it again in the same transaction.
_MIGRATE_3: Final = (
    "DROP INDEX IF EXISTS notes_resting",
    "ALTER TABLE notes RENAME COLUMN rests_on TO written_during",
    "DROP INDEX IF EXISTS log_member",
    "ALTER TABLE pages ADD COLUMN outside INTEGER NOT NULL DEFAULT 0",
    "DROP TRIGGER IF EXISTS versions_never_rewritten",
)


def _migrate(conn: sqlite3.Connection, version: int) -> None:
    """Bring a file at an earlier layout ``version`` to this one, in the caller's transaction.

    Version 1 holds no page, so its page tables are created by :data:`_SCHEMA` like any
    other missing table; versions 2 and 3 hold one, which :func:`_migrate_3` rewrites.

    Raises:
        StoryStoreError: If a stored record is not one the earlier layout wrote, of
            whatever shape: a record read as JSON may hold anything, and none of it
            escapes as another error past the caller's cleanup.
    """
    if version == 1:
        for statement in _MIGRATE_1:
            conn.execute(statement)
    if version in {1, 2}:
        for statement in _MIGRATE_2:
            conn.execute(statement)
    if version in {2, 3}:
        try:
            _migrate_3(conn)
        except (TypeError, ValueError, AttributeError, KeyError) as exc:
            msg = f"a stored page record is not one the earlier layout wrote: {exc}"
            raise StoryStoreError(msg) from exc


def _migrate_3(conn: sqlite3.Connection) -> None:
    """Rewrite the page's records to this layout (ADR-0303 §4:8).

    Every note is kept, and every version and the current page's text. What a version
    recorded of each line's citations, its safety-net notes and its supersession marks
    is dropped, and a version written before records no other story's page version.
    The current page is marked where any of its lines was. A version's mark, which no
    version recorded before, is set where a note it cited or added as a safety net is
    marked, the rule the tidy-up marked a line by; the version that wrote the current
    page is marked as that page is, so the two agree.

    Raises:
        StoryStoreError: If a stored record is not one the earlier layout wrote.
    """
    for statement in _MIGRATE_3:
        conn.execute(statement)
    marked = {row[0] for row in conn.execute("SELECT id FROM notes WHERE outside = 1")}
    records: dict[int, dict[str, Any]] = {}
    for version, record in conn.execute("SELECT version, record FROM versions").fetchall():
        old = _decoded(_json_from, record)
        if not isinstance(old, dict):
            msg = "a stored page version is not a record"
            raise StoryStoreError(msg)
        records[version] = old
    derived = {
        version: any(note in marked for note in _named_in(old)) for version, old in records.items()
    }
    pages: dict[str, tuple[list[dict[str, Any]], bool]] = {}
    for story_id, version, lines in conn.execute(
        "SELECT story_id, version, lines FROM pages"
    ).fetchall():
        old_lines = _decoded(_json_from, lines)
        if not isinstance(old_lines, list) or not all(isinstance(x, dict) for x in old_lines):
            msg = "a stored current page is not a list of lines"
            raise StoryStoreError(msg)
        page_mark = derived.get(version, False) or any(
            line.get("outside") is True for line in old_lines
        )
        derived[version] = page_mark
        pages[story_id] = (old_lines, page_mark)
    for version, old in records.items():
        kept = {
            "took_in_notes": old.get("took_in_notes", []),
            "took_in_episodes": old.get("took_in_episodes", []),
            "read_pages": [],
            "flags": old.get("flags", []),
            "outside": derived[version],
        }
        conn.execute(
            "UPDATE versions SET record = ? WHERE version = ?", (json.dumps(kept), version)
        )
    for story_id, (old_lines, page_mark) in pages.items():
        conn.execute(
            "UPDATE pages SET lines = ?, outside = ? WHERE story_id = ?",
            (
                json.dumps([{"text": line.get("text")} for line in old_lines]),
                int(page_mark),
                story_id,
            ),
        )


def _named_in(record: dict[str, Any]) -> list[object]:
    """The notes an earlier layout's version cited, line by line, and added as safety nets.

    Raises:
        StoryStoreError: If the record's lists are not lists of note ids.
    """
    lines = record.get("lines", [])
    safety_net = record.get("safety_net", [])
    if (
        not isinstance(lines, list)
        or not all(isinstance(line, list) for line in lines)
        or not isinstance(safety_net, list)
    ):
        msg = "a stored page version's citations are not lists of note ids"
        raise StoryStoreError(msg)
    named = [*(note for line in lines for note in line), *safety_net]
    if not all(type(note) is int for note in named):
        msg = "a stored page version's citations are not lists of note ids"
        raise StoryStoreError(msg)
    return named


_ACTIVATION = StoryMemberKind.ACTIVATION.value


class _Refused(Exception):  # noqa: N818 — a control-flow signal, not an error a caller sees
    """Carries a refusal out of a transaction, so the block's writes roll back."""

    def __init__(self, refusal: StoryRefusal) -> None:
        super().__init__(refusal.reason.value)
        self.refusal = refusal


@dataclass(frozen=True, slots=True)
class _Stamp:
    """What every log line an operation appends carries: its actor, trigger and instant."""

    actor: StoryActor
    trigger: str | None
    at: int


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes.

    The store serialises one ``sqlite3`` connection behind an :class:`asyncio.Lock`
    and runs the SQL in a worker thread, which cannot be interrupted. Cancelling the
    awaiting coroutine outright would release the lock while the worker still used
    the connection (ADR-0054, ADR-0060), so a cancellation is absorbed until the
    worker finishes and then re-raised. Deliberately duplicated from
    :mod:`ai_assistant.memory.deferral_store` rather than shared, for the reason that
    module gives; the completion wait is submitted at most once (#697), and every
    failure the worker sees is relayed, ``BaseException`` included (#680).
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


def _new_id() -> str:
    return uuid4().hex


def _to_micros(instant: datetime) -> int:
    """Exact integer microsecond UTC epoch for an aware datetime (issue #289)."""
    delta = instant - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _instant_from(value: object) -> datetime:
    """Rebuild the instant a stored microsecond epoch encodes, refusing a corrupt one.

    Raises:
        StoryStoreError: If the value is not an exact integer or is out of range.
    """
    if type(value) is not int:
        msg = f"a stored story instant is not an integer epoch: {describe_untrusted(value)}"
        raise StoryStoreError(msg)
    try:
        return _EPOCH + timedelta(microseconds=value)
    except (OverflowError, ValueError) as exc:
        msg = f"a stored story instant is out of range: {describe_untrusted(value)}"
        raise StoryStoreError(msg) from exc


def _flag_from(value: object) -> bool:
    """Rebuild a stored ``0``/``1`` flag, refusing anything else.

    Raises:
        StoryStoreError: If the value is not exactly ``0`` or ``1``.
    """
    if type(value) is not int or value not in {0, 1}:
        msg = f"a stored story flag is not 0 or 1: {describe_untrusted(value)}"
        raise StoryStoreError(msg)
    return value == 1


def _decoded[M](build: Callable[..., M], /, *args: Any) -> M:
    """Build a model from stored values, reporting a row that does not validate.

    Raises:
        StoryStoreError: If the stored values do not make a valid model.
    """
    try:
        return build(*args)
    except (ValidationError, ValueError) as exc:
        msg = f"a stored story record does not validate: {exc}"
        raise StoryStoreError(msg) from exc


def _checked_id(value: object) -> str:
    """Validate a story or activation id argument, as :data:`Identifier` does.

    Raises:
        ValueError: If it is not a non-blank encodable string.
    """
    if not isinstance(value, str):
        msg = f"a story id must be a string, got {type(value).__name__}"
        raise ValueError(msg)
    return _IDENTIFIER.validate_python(value)


def _checked_write(actor: object, trigger: object) -> tuple[StoryActor, str | None]:
    """Validate the actor and trigger every write carries.

    Raises:
        ValueError: If the actor is not a :class:`StoryActor` member, or the trigger
            is neither ``None`` nor an identifier.
    """
    if not isinstance(actor, str):
        msg = f"a story actor must be a StoryActor, got {type(actor).__name__}"
        raise ValueError(msg)
    checked_actor = StoryActor(actor)
    checked_trigger = None if trigger is None else _checked_id(trigger)
    return checked_actor, checked_trigger


def _unique[T](items: Sequence[T]) -> list[T]:
    """The items in the order given, each once."""
    return list(dict.fromkeys(items))


# The page's argument checks and its cap rule. Held by each implementation rather
# than in ``core/types.py``: they are this contract's admission rules, not semantics
# intrinsic to the types they read (ADR-0016 §2), and the canonical fake holds its
# own copy, which the conformance suite keeps in step with this one.


def _note_args(
    text: object, *, author: object, written_during: object, outside: object
) -> tuple[str, StoryNoteAuthor, str | None, bool]:
    """Check a note an append writes, as :class:`StoryNote` checks one it holds.

    Nothing writes a note as ``tidy_up`` (ADR-0303 §2:1, §4:6), so it is refused here.

    Raises:
        ValueError: If any of them is malformed, the author is ``tidy_up``, or the
            activation or the mark is one the author does not admit.
    """
    if not isinstance(author, str):
        msg = f"a note's author must be a StoryNoteAuthor, got {type(author).__name__}"
        raise ValueError(msg)
    if StoryNoteAuthor(author) is StoryNoteAuthor.TIDY_UP:
        msg = "the tidy-up writes no note"
        raise ValueError(msg)
    checked = StoryNote(
        note_id=1,
        text=text,  # type: ignore[arg-type]  # validated by the model, which is the point
        author=StoryNoteAuthor(author),
        written_during=written_during,  # type: ignore[arg-type]  # validated by the model
        outside=outside,  # type: ignore[arg-type]  # validated by the model
        written_at=_EPOCH,
    )
    return checked.text, checked.author, checked.written_during, checked.outside


def _answers(answers: object) -> StoryFlagName | None:
    """Snapshot the flag a write answers by revalidation, or ``None`` for none.

    Raises:
        ValueError: If it is neither ``None`` nor a :class:`StoryFlagName`.
    """
    if answers is None:
        return None
    if not isinstance(answers, StoryFlagName):
        msg = f"a write answers a StoryFlagName, got {type(answers).__name__}"
        raise ValueError(msg)
    return StoryFlagName.model_validate(answers.model_dump())


def _grouping(members: Sequence[StoryMember], answers: StoryFlagName | None) -> None:
    """Refuse an activation member on a create or a link answering a flag.

    ADR-0302 §4:3: grouping stories under a larger one names stories only.

    Raises:
        ValueError: If a flag is answered and a member named is an activation.
    """
    if answers is not None and any(m.kind is not StoryMemberKind.STORY for m in members):
        msg = "a create or a link answering a flag names story members only"
        raise ValueError(msg)


def _flag_text(flag: StoryFlagName) -> str:
    """A flag's identity as the canonical JSON text ``log.answers`` holds and is matched on."""
    return json.dumps(flag.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _page_draft(story_id: str, draft: object) -> StoryPageDraft:
    """Snapshot a page write's draft by revalidation, as :func:`story_members` does.

    Raises:
        ValueError: If it is not a :class:`StoryPageDraft`, a flag names the story
            written, or a page version read names it (ADR-0303 §4:2).
    """
    if not isinstance(draft, StoryPageDraft):
        msg = f"a page write takes a StoryPageDraft, got {type(draft).__name__}"
        raise ValueError(msg)
    snapshot = StoryPageDraft.model_validate(draft.model_dump())
    if any(flag.story == story_id for flag in snapshot.flags):
        msg = "a flag names another story, never the one whose page it is raised on"
        raise ValueError(msg)
    if any(read.story == story_id for read in snapshot.read_pages):
        msg = "a page version read is another story's, never the one whose page is written"
        raise ValueError(msg)
    return snapshot


def _leave_outcome(outcome: object) -> StoryDecision:
    """The outcome a ``leave_flag`` records: ``left`` or ``not_applied`` (ADR-0303 §8).

    Raises:
        ValueError: If it is any other outcome, or not a :class:`StoryDecision`.
    """
    if not isinstance(outcome, str):
        msg = f"a decision's outcome must be a StoryDecision, got {type(outcome).__name__}"
        raise ValueError(msg)
    checked = StoryDecision(outcome)
    if checked not in {StoryDecision.LEFT, StoryDecision.NOT_APPLIED}:
        msg = "leave_flag records left or not_applied, the outcomes that change no story"
        raise ValueError(msg)
    return checked


def _move_members(source: str, target: str, members: object) -> tuple[StoryMember, ...]:
    """Snapshot a move's members, refusing what a move cannot carry (ADR-0300 §3:14).

    Raises:
        ValueError: If the two stories are the same, ``members`` is malformed, or a
            member named is a story: a move carries activation members only.
    """
    if source == target:
        msg = "a move is from one story to another"
        raise ValueError(msg)
    named = story_members(members)
    if any(member.kind is not StoryMemberKind.ACTIVATION for member in named):
        msg = "a move carries activation members only"
        raise ValueError(msg)
    return named


def _page_size(draft: StoryPageDraft) -> int:
    """The characters a draft's lines count against ``STORY_PAGE_CAP_CHARS``: all of them.

    ADR-0303 §4:5: every line counts, the lines that came from the user's own notes
    included (§2:6).
    """
    return sum(len(line.text) for line in draft.lines)


class SqliteStoryStore:
    """A persistent ``StoryStore`` backed by ``sqlite3`` (ADR-0289 §1, ADR-0300 §3)."""

    def __init__(
        self,
        *,
        path: Path | str,
        now: Clock = _utcnow,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        """Open (or create) the story store at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
            now: The clock every change is stamped with; injectable for tests and
                guarded by :func:`~ai_assistant.core.clock.checked_clock`.
            new_id: The source a minted story id's suffix is drawn from; the id is
                ``story:`` followed by it.

        Raises:
            StoryStoreError: If the database cannot be opened or prepared, or carries
                a schema version this module neither writes nor migrates.
        """
        self._clock = checked_clock(now, owner="SqliteStoryStore")
        self._new_id = new_id
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    # --- opening -------------------------------------------------------------

    def _setup(self) -> sqlite3.Connection:
        """Open the connection and create the schema, or fail with the seam's error."""
        try:
            # Autocommit, so every transaction below is an explicit BEGIN ... COMMIT
            # this module controls rather than one the driver opens deferred.
            conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        except (sqlite3.Error, OSError, ValueError) as exc:
            msg = f"failed to open story store at {self._path!r}: {exc}"
            raise StoryStoreError(msg) from exc
        try:
            # Writing a new current page discards the old one's text (ADR-0300 §3:6),
            # so the pages a replaced row frees are zeroed rather than left holding
            # it. Outside the transaction: a pragma issued inside one is ignored.
            conn.execute("PRAGMA secure_delete = ON")
            # Restricted before the first write, so no journal is ever written with
            # the process umask (ADR-0004 §4).
            self._restrict_permissions()
            with transaction(conn, "prepare the story store", error=StoryStoreError):
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version not in {0, 1, 2, 3, _SCHEMA_VERSION}:
                    msg = (
                        f"the story store at {self._path!r} carries schema version "
                        f"{version}, and this build writes {_SCHEMA_VERSION}"
                    )
                    raise StoryStoreError(msg)
                _migrate(conn, version)
                for statement in _SCHEMA:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        except (sqlite3.Error, OSError, StoryStoreError) as exc:
            conn.close()  # never leak the connection when opening fails
            if isinstance(exc, StoryStoreError):
                raise
            msg = f"failed to open story store at {self._path!r}: {exc}"
            raise StoryStoreError(msg) from exc
        return conn

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case and a symlinked one is skipped rather
        than followed, as :class:`~ai_assistant.memory.deferral_store.
        SqliteDeferralStore` does and for its reasons. A no-op in memory.
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
        """The guarded clock's reading, as this store's own error."""
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise StoryStoreError(str(exc)) from exc

    def _transaction(self, what: str, *, immediate: bool = True) -> AbstractContextManager[Any]:
        return transaction(self._conn, what, error=StoryStoreError, immediate=immediate)

    @staticmethod
    def _header(conn: sqlite3.Connection, story_id: str) -> StoryHeader | None:
        row = conn.execute(
            "SELECT id, created_at, merged_into FROM stories WHERE id = ?", (story_id,)
        ).fetchone()
        if row is None:
            return None
        return _decoded(_header_from, row)

    @staticmethod
    def _holds(conn: sqlite3.Connection, story_id: str, member: StoryMember) -> bool:
        return (
            conn.execute(
                "SELECT 1 FROM members WHERE story_id = ? AND kind = ? AND member_id = ?",
                (story_id, member.kind.value, member.id),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _member_rows(conn: sqlite3.Connection, story_id: str) -> list[StoryMember]:
        rows = conn.execute(
            "SELECT kind, member_id FROM members WHERE story_id = ? ORDER BY position",
            (story_id,),
        ).fetchall()
        return [_decoded(_member_from, row) for row in rows]

    @staticmethod
    def _holders(conn: sqlite3.Connection, story_id: str) -> list[str]:
        """The stories holding ``story_id`` as a member, in the order they linked it."""
        rows = conn.execute(
            "SELECT story_id FROM members WHERE kind = ? AND member_id = ? ORDER BY position",
            (StoryMemberKind.STORY.value, story_id),
        ).fetchall()
        return [row[0] for row in rows]

    @staticmethod
    def _path_down(conn: sqlite3.Connection, start: str, target: str) -> list[str] | None:
        """A chain of stories from ``start`` down to ``target`` through membership.

        Breadth-first, so the chain reported is a shortest one. ``None`` where
        ``target`` is not reachable from ``start``.
        """
        parents: dict[str, str | None] = {start: None}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            if current == target:
                chain = [current]
                while (above := parents[chain[-1]]) is not None:
                    chain.append(above)
                return chain[::-1]
            rows = conn.execute(
                "SELECT member_id FROM members WHERE story_id = ? AND kind = ? ORDER BY position",
                (current, StoryMemberKind.STORY.value),
            ).fetchall()
            for (child,) in rows:
                if child not in parents:
                    parents[child] = current
                    queue.append(child)
        return None

    def _story_refusal(self, conn: sqlite3.Connection, story_id: str) -> StoryRefusal | None:
        """Refuse a story that is unknown or merged, as written to or as a member."""
        header = self._header(conn, story_id)
        if header is None:
            return StoryRefusal(reason=StoryRefusalReason.UNKNOWN_STORY, story_id=story_id)
        if header.merged_into is not None:
            return StoryRefusal(
                reason=StoryRefusalReason.MERGED_STORY,
                story_id=story_id,
                merged_into=header.merged_into,
            )
        return None

    def _members_refusal(
        self, conn: sqlite3.Connection, members: Sequence[StoryMember]
    ) -> StoryRefusal | None:
        """Refuse a write naming an unknown or merged story as a member."""
        for member in members:
            if member.kind is StoryMemberKind.STORY and (
                refused := self._story_refusal(conn, member.id)
            ):
                return refused
        return None

    @staticmethod
    def _tick(conn: sqlite3.Connection) -> int:
        """Advance the page's counter and return its new value (see the module docstring)."""
        conn.execute("UPDATE ticks SET value = value + 1 WHERE only = 0")
        return SqliteStoryStore._ticks(conn)

    @staticmethod
    def _ticks(conn: sqlite3.Connection) -> int:
        """The page's counter as it stands."""
        row = conn.execute("SELECT value FROM ticks WHERE only = 0").fetchone()
        if row is None or type(row[0]) is not int or row[0] < 0:
            msg = "the story store's page counter is missing or corrupt"
            raise StoryStoreError(msg)
        return int(row[0])

    @staticmethod
    def _append(  # noqa: PLR0913 — the connection, the line's story and change, and its fields
        conn: sqlite3.Connection,
        story_id: str,
        change: StoryChange,
        stamp: _Stamp,
        *,
        member: StoryMember | None = None,
        other: str | None = None,
        decision: tuple[StoryFlagName, StoryDecision] | None = None,
    ) -> int:
        cursor = conn.execute(
            "INSERT INTO log(story_id, change, member_kind, member_id, other_story, actor, "
            "trigger_id, at, answers, outcome) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                story_id,
                change.value,
                None if member is None else member.kind.value,
                None if member is None else member.id,
                other,
                stamp.actor.value,
                stamp.trigger,
                stamp.at,
                None if decision is None else _flag_text(decision[0]),
                None if decision is None else decision[1].value,
            ),
        )
        sequence = cursor.lastrowid
        if sequence is None:  # pragma: no cover — an INSERT always sets it
            msg = "the story log did not report the sequence it assigned"
            raise StoryStoreError(msg)
        return sequence

    # --- decisions on flags (ADR-0302 §§2-4) ---------------------------------

    def _followed(self, conn: sqlite3.Connection, story_id: str) -> str:
        """The story ``story_id`` was merged into, through every merge, or itself."""
        seen = {story_id}
        while True:
            header = self._header(conn, story_id)
            if header is None:
                msg = f"the story store has no story {story_id!r} that its records name"
                raise StoryStoreError(msg)
            onward = header.merged_into
            if onward is None:
                return story_id
            if onward in seen:
                msg = f"story {story_id!r} is merged into a chain that loops"
                raise StoryStoreError(msg)
            seen.add(onward)
            story_id = onward

    def _flag_refusal(self, conn: sqlite3.Connection, flag: StoryFlagName) -> StoryRefusal | None:
        """``unknown_flag``, then ``already_decided``, read off the store's own records.

        A flag named by an activation is never held: understanding raises no flag
        (ADR-0303 §8).
        """
        if flag.activation is not None:
            held = False
        else:
            row = conn.execute(
                "SELECT version, written_at, record FROM versions WHERE version = ? "
                "AND story_id = ?",
                (flag.version, flag.story),
            ).fetchone()
            held = row is not None and flag.flag in _decoded(_version_from, row).flags
        if not held:
            return StoryRefusal(reason=StoryRefusalReason.UNKNOWN_FLAG, flag=flag)
        answered = conn.execute(
            "SELECT 1 FROM log WHERE answers = ? AND change = ? LIMIT 1",
            (_flag_text(flag), StoryChange.DECIDED.value),
        ).fetchone()
        if answered is not None:
            return StoryRefusal(reason=StoryRefusalReason.ALREADY_DECIDED, flag=flag)
        return None

    def _concerned(self, conn: sqlite3.Connection, flag: StoryFlagName) -> list[str]:
        """The stories a held flag concerns, followed through merges, each once (§2:3)."""
        if flag.story is None or flag.flag is None:  # pragma: no cover — never held (§8)
            msg = "a held flag names its story and the flag"
            raise ValueError(msg)
        raised = [flag.story] if flag.flag.story is None else [flag.story, flag.flag.story]
        return _unique([self._followed(conn, story_id) for story_id in raised])

    def _decide(
        self,
        conn: sqlite3.Connection,
        flag: StoryFlagName,
        outcome: StoryDecision,
        stamp: _Stamp,
    ) -> list[str]:
        """Write one ``decided`` line on each story the flag concerns, as they now stand."""
        decided = _Stamp(actor=stamp.actor, trigger=None, at=stamp.at)
        concerned = self._concerned(conn, flag)
        for story_id in concerned:
            self._append(conn, story_id, StoryChange.DECIDED, decided, decision=(flag, outcome))
        return concerned

    def _add(
        self, conn: sqlite3.Connection, story_id: str, member: StoryMember, stamp: _Stamp
    ) -> None:
        position = self._append(conn, story_id, StoryChange.ADDED, stamp, member=member)
        # An activation member is pending on the story it comes to (ADR-0300 §3:8).
        pending = self._tick(conn) if member.kind is StoryMemberKind.ACTIVATION else None
        conn.execute(
            "INSERT INTO members(story_id, kind, member_id, position, linked_at, actor, "
            "pending_since) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (
                story_id,
                member.kind.value,
                member.id,
                position,
                stamp.at,
                stamp.actor.value,
                pending,
            ),
        )

    def _remove(
        self, conn: sqlite3.Connection, story_id: str, member: StoryMember, stamp: _Stamp
    ) -> None:
        conn.execute(
            "DELETE FROM members WHERE story_id = ? AND kind = ? AND member_id = ?",
            (story_id, member.kind.value, member.id),
        )
        self._append(conn, story_id, StoryChange.REMOVED, stamp, member=member)

    def _carry_notes(self, conn: sqlite3.Connection, note_ids: Sequence[int], to: str) -> None:
        """Move notes to story ``to``, each pending there from now (ADR-0300 §3:8)."""
        for note_id in note_ids:
            conn.execute(
                "UPDATE notes SET story_id = ?, pending_since = ? WHERE id = ?",
                (to, self._tick(conn), note_id),
            )

    @staticmethod
    def _named_notes(conn: sqlite3.Connection, story_id: str, named: Sequence[int]) -> list[int]:
        """The notes named that ``story_id`` holds, in note order (ADR-0303 §6:2).

        Whoever wrote them; a name it does not hold is passed over.
        """
        return sorted(
            note_id
            for note_id in _unique(named)
            if conn.execute(
                "SELECT 1 FROM notes WHERE id = ? AND story_id = ?", (note_id, story_id)
            ).fetchone()
            is not None
        )

    def _mint(self, conn: sqlite3.Connection, stamp: _Stamp) -> str:
        """Mint a story id, write its row and log ``created``."""
        suffix = self._new_id()
        if type(suffix) is not str or not suffix.strip():
            msg = f"the story id source returned an unusable id: {describe_untrusted(suffix)}"
            raise StoryStoreError(msg)
        story_id = _checked_id(STORY_ID_PREFIX + suffix.strip())
        if self._header(conn, story_id) is not None:
            msg = f"the story id source minted {story_id!r}, which the store already holds"
            raise StoryStoreError(msg)
        sequence = self._append(conn, story_id, StoryChange.CREATED, stamp)
        conn.execute(
            "INSERT INTO stories(id, created_seq, created_at, merged_into) VALUES(?, ?, ?, NULL)",
            (story_id, sequence, stamp.at),
        )
        return story_id

    async def _locked[T](self, fn: Callable[..., T], /, *args: object) -> T:
        async with self._lock:
            return await _run_to_completion(fn, *args)

    def _stamp(self, actor: StoryActor, trigger: str | None) -> _Stamp:
        return _Stamp(actor=actor, trigger=trigger, at=_to_micros(self._now()))

    # --- writes --------------------------------------------------------------

    async def create(
        self,
        members: Sequence[StoryMember],
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
        answers: StoryFlagName | None = None,
    ) -> StoryOutcome:
        """Mint a story holding ``members`` (ADR-0289 §3, ADR-0302 §4)."""
        named = story_members(members)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        flag = _answers(answers)
        _grouping(named, flag)
        return await self._locked(self._create_sync, named, checked_actor, checked_trigger, flag)

    def _create_sync(
        self,
        members: tuple[StoryMember, ...],
        actor: StoryActor,
        trigger: str | None,
        flag: StoryFlagName | None,
    ) -> StoryOutcome:
        if not members:
            return StoryOutcome(refusal=StoryRefusal(reason=StoryRefusalReason.NO_MEMBERS))
        stamp = self._stamp(actor, trigger)
        with self._transaction("create a story") as conn:
            if refused := self._members_refusal(conn, members):
                return StoryOutcome(refusal=refused)
            if flag is not None and (refused := self._flag_refusal(conn, flag)):
                return StoryOutcome(refusal=refused)
            story_id = self._mint(conn, stamp)
            unique = _unique(members)
            for member in unique:
                self._add(conn, story_id, member, stamp)
            decided = [] if flag is None else self._decide(conn, flag, StoryDecision.GROUPED, stamp)
        return StoryOutcome(story_id=story_id, logged=1 + len(unique) + len(decided))

    async def link(
        self,
        story_id: Identifier,
        members: Sequence[StoryMember],
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
        answers: StoryFlagName | None = None,
    ) -> StoryOutcome:
        """Add ``members`` to a story (ADR-0289 §3, ADR-0302 §4)."""
        target = _checked_id(story_id)
        named = story_members(members)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        flag = _answers(answers)
        _grouping(named, flag)
        return await self._locked(
            self._link_sync, target, named, checked_actor, checked_trigger, flag
        )

    def _link_sync(
        self,
        story_id: str,
        members: tuple[StoryMember, ...],
        actor: StoryActor,
        trigger: str | None,
        flag: StoryFlagName | None,
    ) -> StoryOutcome:
        if not members:
            return StoryOutcome(refusal=StoryRefusal(reason=StoryRefusalReason.NO_MEMBERS))
        stamp = self._stamp(actor, trigger)
        with self._transaction("link to a story") as conn:
            if refused := self._story_refusal(conn, story_id) or self._members_refusal(
                conn, members
            ):
                return StoryOutcome(refusal=refused)
            fresh = [m for m in _unique(members) if not self._holds(conn, story_id, m)]
            for member in fresh:
                if member.kind is not StoryMemberKind.STORY:
                    continue
                chain = self._path_down(conn, member.id, story_id)
                if chain is not None:
                    # The story would hold ``member``, which already reaches the story:
                    # the loop is the story, then the chain down from the member to the
                    # story that holds it — just the story, where it would hold itself.
                    return StoryOutcome(
                        refusal=StoryRefusal(
                            reason=StoryRefusalReason.LOOP,
                            story_id=story_id,
                            loop=(story_id, *chain[:-1]),
                        )
                    )
            if flag is not None and (refused := self._flag_refusal(conn, flag)):
                return StoryOutcome(refusal=refused)
            for member in fresh:
                self._add(conn, story_id, member, stamp)
            decided = [] if flag is None else self._decide(conn, flag, StoryDecision.GROUPED, stamp)
        return StoryOutcome(story_id=story_id, logged=len(fresh) + len(decided))

    async def unlink(
        self,
        story_id: Identifier,
        members: Sequence[StoryMember],
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
    ) -> StoryOutcome:
        """Remove ``members`` from a story (ADR-0289 §3)."""
        target = _checked_id(story_id)
        named = story_members(members)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        return await self._locked(self._unlink_sync, target, named, checked_actor, checked_trigger)

    def _unlink_sync(
        self,
        story_id: str,
        members: tuple[StoryMember, ...],
        actor: StoryActor,
        trigger: str | None,
    ) -> StoryOutcome:
        if not members:
            return StoryOutcome(refusal=StoryRefusal(reason=StoryRefusalReason.NO_MEMBERS))
        stamp = self._stamp(actor, trigger)
        with self._transaction("unlink from a story") as conn:
            if refused := self._story_refusal(conn, story_id) or self._members_refusal(
                conn, members
            ):
                return StoryOutcome(refusal=refused)
            held = [m for m in _unique(members) if self._holds(conn, story_id, m)]
            for member in held:
                self._remove(conn, story_id, member, stamp)
        return StoryOutcome(story_id=story_id, logged=len(held))

    async def merge(
        self,
        story_id: Identifier,
        into: Identifier,
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
        answers: StoryFlagName | None = None,
    ) -> StoryOutcome:
        """Merge story ``story_id`` into story ``into`` (ADR-0289 §3, ADR-0300 §3)."""
        absorbed = _checked_id(story_id)
        target = _checked_id(into)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        flag = _answers(answers)
        return await self._locked(
            self._merge_sync, absorbed, target, checked_actor, checked_trigger, flag
        )

    def _merge_sync(
        self,
        absorbed: str,
        target: str,
        actor: StoryActor,
        trigger: str | None,
        flag: StoryFlagName | None,
    ) -> StoryOutcome:
        stamp = self._stamp(actor, trigger)
        try:
            with self._transaction("merge stories") as conn:
                if refused := self._story_refusal(conn, absorbed) or self._story_refusal(
                    conn, target
                ):
                    return StoryOutcome(refusal=refused)
                if absorbed == target:
                    return StoryOutcome(
                        refusal=StoryRefusal(
                            reason=StoryRefusalReason.SELF_MERGE, story_id=absorbed
                        )
                    )
                # The flag is read off the records before the merge writes anything,
                # and reported only after the merge's own loop check (ADR-0302 §4:5).
                flag_refused = None if flag is None else self._flag_refusal(conn, flag)
                logged = self._merge_writes(conn, absorbed, target, stamp)
                # Every edge the merge added touches the target — it gained the
                # absorbed story's members, and the absorbed story's holders gained
                # it — so any loop the merge closed runs through the target.
                for child in self._story_children(conn, target):
                    chain = self._path_down(conn, child, target)
                    if chain is not None:
                        raise _Refused(
                            StoryRefusal(
                                reason=StoryRefusalReason.LOOP,
                                story_id=target,
                                loop=(target, *chain[:-1]),
                            )
                        )
                if flag_refused is not None:
                    raise _Refused(flag_refused)
                if flag is not None:
                    logged += len(self._decide(conn, flag, StoryDecision.MERGED, stamp))
        except _Refused as refused:
            return StoryOutcome(refusal=refused.refusal)
        return StoryOutcome(story_id=target, logged=logged)

    @staticmethod
    def _story_children(conn: sqlite3.Connection, story_id: str) -> list[str]:
        rows = conn.execute(
            "SELECT member_id FROM members WHERE story_id = ? AND kind = ? ORDER BY position",
            (story_id, StoryMemberKind.STORY.value),
        ).fetchall()
        return [row[0] for row in rows]

    def _merge_writes(
        self, conn: sqlite3.Connection, absorbed: str, target: str, stamp: _Stamp
    ) -> int:
        """Apply a merge's writes, returning how many log lines they appended."""
        self._append(conn, absorbed, StoryChange.MERGED_INTO, stamp, other=target)
        self._append(conn, target, StoryChange.ABSORBED, stamp, other=absorbed)
        logged = 2
        target_member = StoryMember(kind=StoryMemberKind.STORY, id=target)
        for member in self._member_rows(conn, absorbed):
            self._remove(conn, absorbed, member, stamp)
            logged += 1
            if member == target_member or self._holds(conn, target, member):
                continue
            self._add(conn, target, member, stamp)
            logged += 1
        absorbed_member = StoryMember(kind=StoryMemberKind.STORY, id=absorbed)
        for holder in self._holders(conn, absorbed):
            self._remove(conn, holder, absorbed_member, stamp)
            logged += 1
            if holder == target or self._holds(conn, holder, target_member):
                continue
            self._add(conn, holder, target_member, stamp)
            logged += 1
        conn.execute("UPDATE stories SET merged_into = ? WHERE id = ?", (target, absorbed))
        # The absorbed story's notes go with it (ADR-0300 §3:12).
        rows = conn.execute(
            "SELECT id FROM notes WHERE story_id = ? ORDER BY id", (absorbed,)
        ).fetchall()
        self._carry_notes(conn, [row[0] for row in rows], target)
        return logged

    async def split(  # noqa: PLR0913 — ADR-0302 §4:2 adds ``answers`` as a keyword to this operation
        self,
        story_id: Identifier,
        members: Sequence[StoryMember],
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
        notes: Sequence[StoryNoteId] = (),
        answers: StoryFlagName | None = None,
    ) -> StoryOutcome:
        """Move a non-empty subset of a story's members into a new story (ADR-0289 §3)."""
        source = _checked_id(story_id)
        named = story_members(members)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        named_notes = story_note_ids(notes)
        flag = _answers(answers)
        return await self._locked(
            self._split_sync, source, named, checked_actor, checked_trigger, named_notes, flag
        )

    def _split_sync(  # noqa: PLR0913 — the story, its members, the stamp's parts, notes, flag
        self,
        story_id: str,
        members: tuple[StoryMember, ...],
        actor: StoryActor,
        trigger: str | None,
        notes: tuple[int, ...],
        flag: StoryFlagName | None,
    ) -> StoryOutcome:
        if not members:
            return StoryOutcome(refusal=StoryRefusal(reason=StoryRefusalReason.NO_MEMBERS))
        stamp = self._stamp(actor, trigger)
        with self._transaction("split a story") as conn:
            if refused := self._story_refusal(conn, story_id) or self._members_refusal(
                conn, members
            ):
                return StoryOutcome(refusal=refused)
            for member in members:
                if not self._holds(conn, story_id, member):
                    return StoryOutcome(
                        refusal=StoryRefusal(
                            reason=StoryRefusalReason.NOT_A_MEMBER,
                            story_id=story_id,
                            member=member,
                        )
                    )
            moving = set(members)
            moved = [m for m in self._member_rows(conn, story_id) if m in moving]
            carried = self._named_notes(conn, story_id, notes)
            if flag is not None and (refused := self._flag_refusal(conn, flag)):
                return StoryOutcome(refusal=refused)
            split_off = self._mint(conn, stamp)
            self._append(conn, story_id, StoryChange.SPLIT_OFF, stamp, other=split_off)
            self._append(conn, split_off, StoryChange.SPLIT_OFF, stamp, other=story_id)
            for member in moved:
                self._remove(conn, story_id, member, stamp)
                self._add(conn, split_off, member, stamp)
            self._carry_notes(conn, carried, split_off)
            decided = [] if flag is None else self._decide(conn, flag, StoryDecision.SPLIT, stamp)
        return StoryOutcome(story_id=split_off, logged=3 + 2 * len(moved) + len(decided))

    async def move(  # noqa: PLR0913 — ADR-0302 §4:2 and ADR-0303 §6:2 add keywords to this operation
        self,
        story_id: Identifier,
        to: Identifier,
        members: Sequence[StoryMember],
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
        notes: Sequence[StoryNoteId] = (),
        answers: StoryFlagName | None = None,
    ) -> StoryOutcome:
        """Move activation members from one story to another (ADR-0300 §3, ADR-0303 §6)."""
        source = _checked_id(story_id)
        target = _checked_id(to)
        named = _move_members(source, target, members)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        named_notes = story_note_ids(notes)
        flag = _answers(answers)
        return await self._locked(
            self._move_sync,
            source,
            target,
            named,
            checked_actor,
            checked_trigger,
            named_notes,
            flag,
        )

    def _move_sync(  # noqa: PLR0913 — both stories, the members, the stamp's parts, notes, flag
        self,
        source: str,
        target: str,
        members: tuple[StoryMember, ...],
        actor: StoryActor,
        trigger: str | None,
        notes: tuple[int, ...],
        flag: StoryFlagName | None,
    ) -> StoryOutcome:
        if not members:
            return StoryOutcome(refusal=StoryRefusal(reason=StoryRefusalReason.NO_MEMBERS))
        stamp = self._stamp(actor, trigger)
        with self._transaction("move story members") as conn:
            if refused := self._story_refusal(conn, source) or self._story_refusal(conn, target):
                return StoryOutcome(refusal=refused)
            for member in members:
                if not self._holds(conn, source, member):
                    return StoryOutcome(
                        refusal=StoryRefusal(
                            reason=StoryRefusalReason.NOT_A_MEMBER,
                            story_id=source,
                            member=member,
                        )
                    )
            moving = set(members)
            moved = [m for m in self._member_rows(conn, source) if m in moving]
            carried = self._named_notes(conn, source, notes)
            if flag is not None and (refused := self._flag_refusal(conn, flag)):
                return StoryOutcome(refusal=refused)
            logged = 0
            for member in moved:
                self._remove(conn, source, member, stamp)
                logged += 1
                if self._holds(conn, target, member):
                    continue
                self._add(conn, target, member, stamp)
                logged += 1
            self._carry_notes(conn, carried, target)
            if flag is not None:
                logged += len(self._decide(conn, flag, StoryDecision.MOVED, stamp))
        return StoryOutcome(story_id=target, logged=logged)

    async def leave_flag(
        self,
        flag: StoryFlagName,
        *,
        actor: StoryActor,
        outcome: StoryDecision = StoryDecision.LEFT,
    ) -> StoryOutcome:
        """Record a decision on a flag that changed no story (ADR-0302 §4:1, ADR-0303 §8)."""
        checked = _answers(flag)
        if checked is None:
            msg = "leave_flag takes the flag it decides"
            raise ValueError(msg)
        checked_actor, _ = _checked_write(actor, None)
        recorded = _leave_outcome(outcome)
        return await self._locked(self._leave_flag_sync, checked, checked_actor, recorded)

    def _leave_flag_sync(
        self, flag: StoryFlagName, actor: StoryActor, outcome: StoryDecision
    ) -> StoryOutcome:
        stamp = self._stamp(actor, None)
        with self._transaction("leave a flag") as conn:
            if refused := self._flag_refusal(conn, flag):
                return StoryOutcome(refusal=refused)
            decided = self._decide(conn, flag, outcome, stamp)
        return StoryOutcome(story_id=decided[0], logged=len(decided))

    # --- the page: writes (ADR-0300 §3) --------------------------------------

    async def append_note(
        self,
        story_id: Identifier,
        text: str,
        *,
        author: StoryNoteAuthor,
        written_during: Identifier | None = None,
        outside: bool = False,
    ) -> StoryNoteOutcome:
        """Write a note to a story's page, pending there (ADR-0303 §2, §4:7)."""
        target = _checked_id(story_id)
        checked = _note_args(text, author=author, written_during=written_during, outside=outside)
        return await self._locked(self._append_note_sync, target, *checked)

    def _append_note_sync(
        self,
        story_id: str,
        text: str,
        author: StoryNoteAuthor,
        written_during: str | None,
        outside: bool,
    ) -> StoryNoteOutcome:
        at = self._now()
        with self._transaction("write a story note") as conn:
            if refused := self._page_refusal(conn, story_id):
                return StoryNoteOutcome(refusal=refused)
            note_id = self._tick(conn)
            note = _decoded(
                lambda: StoryNote(
                    note_id=note_id,
                    text=text,
                    author=author,
                    written_during=written_during,
                    outside=outside,
                    written_at=_instant_from(_to_micros(at)),
                )
            )
            self._insert_note(conn, story_id, note, pending=note_id)
        return StoryNoteOutcome(note=note)

    @staticmethod
    def _insert_note(
        conn: sqlite3.Connection, story_id: str, note: StoryNote, *, pending: int | None
    ) -> None:
        conn.execute(
            "INSERT INTO notes(id, story_id, text, author, written_during, outside, "
            "written_at, pending_since) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                note.note_id,
                story_id,
                note.text,
                note.author.value,
                note.written_during,
                int(note.outside),
                _to_micros(note.written_at),
                pending,
            ),
        )

    def _page_refusal(self, conn: sqlite3.Connection, story_id: str) -> StoryPageRefusal | None:
        """Refuse a page write to a story that is unknown or merged."""
        header = self._header(conn, story_id)
        if header is None:
            return StoryPageRefusal(reason=StoryPageRefusalReason.UNKNOWN_STORY, story_id=story_id)
        if header.merged_into is not None:
            return StoryPageRefusal(
                reason=StoryPageRefusalReason.MERGED_STORY,
                story_id=story_id,
                merged_into=header.merged_into,
            )
        return None

    async def write_page(
        self,
        story_id: Identifier,
        draft: StoryPageDraft,
        *,
        as_of: int,
    ) -> StoryPageOutcome:
        """Write a new current page and its version, and no note (ADR-0303 §4)."""
        target = _checked_id(story_id)
        checked = _page_draft(target, draft)
        basis = check_story_as_of(as_of)
        return await self._locked(self._write_page_sync, target, checked, basis)

    def _write_page_sync(
        self, story_id: str, draft: StoryPageDraft, as_of: int
    ) -> StoryPageOutcome:
        at = _instant_from(_to_micros(self._now()))
        with self._transaction("write a story's page") as conn:
            if refused := self._page_refusal(conn, story_id):
                return StoryPageOutcome(refusal=refused)
            if as_of > self._ticks(conn):
                msg = "a page's as_of is one no read of this store has returned"
                raise ValueError(msg)
            if refused := self._draft_refusal(conn, story_id, draft, as_of):
                return StoryPageOutcome(refusal=refused)
            version = self._page_writes(conn, story_id, draft, as_of, at)
        return StoryPageOutcome(version=version)

    def _draft_refusal(
        self, conn: sqlite3.Connection, story_id: str, draft: StoryPageDraft, as_of: int
    ) -> StoryPageRefusal | None:
        """The first of the page's refusals a draft meets after the story's own, if any.

        ADR-0303 §4:4: ``page_moved_on``, a flag's unknown story, a page version read
        naming an unknown story (§4:2), ``not_held``, ``over_cap``.

        Raises:
            ValueError: If a page version read names a version its story's log does not
                hold: an identity naming nothing is malformed (§4:2).
        """
        newest = conn.execute(
            "SELECT MAX(version) FROM versions WHERE story_id = ?", (story_id,)
        ).fetchone()[0]
        if newest is not None and newest > as_of:
            return StoryPageRefusal(reason=StoryPageRefusalReason.PAGE_MOVED_ON, story_id=story_id)
        for flag in draft.flags:
            if flag.story is not None and self._header(conn, flag.story) is None:
                return StoryPageRefusal(
                    reason=StoryPageRefusalReason.UNKNOWN_STORY, story_id=flag.story
                )
        for read in draft.read_pages:
            if self._header(conn, read.story) is None:
                return StoryPageRefusal(
                    reason=StoryPageRefusalReason.UNKNOWN_STORY, story_id=read.story
                )
            if (
                conn.execute(
                    "SELECT 1 FROM versions WHERE version = ? AND story_id = ?",
                    (read.version, read.story),
                ).fetchone()
                is None
            ):
                msg = "a page version read names a version its story's log does not hold"
                raise ValueError(msg)
        if refused := self._not_held(conn, story_id, draft):
            return refused
        if _page_size(draft) > STORY_PAGE_CAP_CHARS:
            return StoryPageRefusal(reason=StoryPageRefusalReason.OVER_CAP, story_id=story_id)
        return None

    def _not_held(
        self, conn: sqlite3.Connection, story_id: str, draft: StoryPageDraft
    ) -> StoryPageRefusal | None:
        """The first thing a draft takes in that its story does not hold.

        ADR-0302 §7: the episodes taken in, then the notes taken in, each against what
        the story holds inside the write's own transaction.
        """
        for activation in draft.took_in_episodes:
            member = StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation)
            if not self._holds(conn, story_id, member):
                return StoryPageRefusal(
                    reason=StoryPageRefusalReason.NOT_HELD,
                    story_id=story_id,
                    activation=activation,
                )
        for note_id in draft.took_in_notes:
            row = conn.execute(
                "SELECT 1 FROM notes WHERE id = ? AND story_id = ?", (note_id, story_id)
            ).fetchone()
            if row is None:
                return StoryPageRefusal(
                    reason=StoryPageRefusalReason.NOT_HELD, story_id=story_id, note=note_id
                )
        return None

    def _page_writes(
        self,
        conn: sqlite3.Connection,
        story_id: str,
        draft: StoryPageDraft,
        as_of: int,
        at: datetime,
    ) -> StoryPageVersion:
        """Take in, replace the page and append the version, writing no note (ADR-0303 §4)."""
        took_notes = [
            note_id
            for note_id in _unique(draft.took_in_notes)
            if conn.execute(
                "UPDATE notes SET pending_since = NULL WHERE id = ? AND story_id = ? "
                "AND pending_since IS NOT NULL AND pending_since <= ?",
                (note_id, story_id, as_of),
            ).rowcount
        ]
        took_episodes = [
            activation
            for activation in _unique(draft.took_in_episodes)
            if conn.execute(
                "UPDATE members SET pending_since = NULL WHERE story_id = ? AND kind = ? "
                "AND member_id = ? AND pending_since IS NOT NULL AND pending_since <= ?",
                (story_id, _ACTIVATION, activation, as_of),
            ).rowcount
        ]
        version = StoryPageVersion(
            version=self._tick(conn),
            written_at=at,
            took_in_notes=tuple(took_notes),
            took_in_episodes=tuple(took_episodes),
            read_pages=tuple(_unique(draft.read_pages)),
            flags=draft.flags,
            outside=draft.outside,
        )
        record = version.model_dump(mode="json", exclude={"version", "written_at"})
        conn.execute(
            "INSERT INTO versions(version, story_id, written_at, record) VALUES(?, ?, ?, ?)",
            (version.version, story_id, _to_micros(at), json.dumps(record)),
        )
        conn.execute(
            "INSERT INTO pages(story_id, version, written_at, lines, outside) "
            "VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(story_id) DO UPDATE SET version = excluded.version, "
            "written_at = excluded.written_at, lines = excluded.lines, "
            "outside = excluded.outside",
            (
                story_id,
                version.version,
                _to_micros(at),
                json.dumps([line.model_dump(mode="json") for line in draft.lines]),
                int(draft.outside),
            ),
        )
        return version

    # --- reads ---------------------------------------------------------------

    async def header(self, story_id: Identifier) -> StoryHeader | None:
        """Read a story's header (ADR-0289 §3)."""
        target = _checked_id(story_id)
        return await self._locked(self._header_sync, target)

    def _header_sync(self, story_id: str) -> StoryHeader | None:
        with self._transaction("read a story", immediate=False) as conn:
            return self._header(conn, story_id)

    async def view(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryViewPage | None:
        """Read a page of a story's clean view, in link order (ADR-0289 §3)."""
        target = _checked_id(story_id)
        check_story_page(cursor, limit)
        return await self._locked(self._view_sync, target, cursor, limit)

    def _view_sync(self, story_id: str, cursor: int | None, limit: int) -> StoryViewPage | None:
        with self._transaction("read a story's view", immediate=False) as conn:
            header = self._header(conn, story_id)
            if header is None:
                return None
            count = conn.execute(
                "SELECT COUNT(*) FROM members WHERE story_id = ?", (story_id,)
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT position, kind, member_id, linked_at, actor FROM members "
                "WHERE story_id = ? AND position > ? ORDER BY position LIMIT ?",
                (story_id, -1 if cursor is None else cursor, limit + 1),
            ).fetchall()
        entries = [_decoded(_entry_from, row) for row in rows[:limit]]
        more = len(rows) > limit
        return _decoded(
            lambda: StoryViewPage(
                story=header,
                member_count=count,
                entries=tuple(entries),
                next_cursor=entries[-1].position if more else None,
            )
        )

    async def log(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryLogPage | None:
        """Read a page of a story's change log, in sequence order (ADR-0289 §3)."""
        target = _checked_id(story_id)
        check_story_page(cursor, limit)
        return await self._locked(self._log_sync, target, cursor, limit)

    def _log_sync(self, story_id: str, cursor: int | None, limit: int) -> StoryLogPage | None:
        with self._transaction("read a story's log", immediate=False) as conn:
            header = self._header(conn, story_id)
            if header is None:
                return None
            rows = conn.execute(
                "SELECT sequence, story_id, change, member_kind, member_id, other_story, "
                "actor, trigger_id, at, answers, outcome FROM log "
                "WHERE story_id = ? AND sequence > ? ORDER BY sequence LIMIT ?",
                (story_id, -1 if cursor is None else cursor, limit + 1),
            ).fetchall()
        lines = [_decoded(_line_from, row) for row in rows[:limit]]
        more = len(rows) > limit
        return _decoded(
            lambda: StoryLogPage(
                story=header,
                lines=tuple(lines),
                next_cursor=lines[-1].sequence if more else None,
            )
        )

    async def stories(
        self,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryPage:
        """Read a page of every story the store holds, newest first (ADR-0289 §3)."""
        check_story_page(cursor, limit)
        return await self._locked(self._stories_sync, cursor, limit)

    def _stories_sync(self, cursor: int | None, limit: int) -> StoryPage:
        with self._transaction("list stories", immediate=False) as conn:
            if cursor is None:
                rows = conn.execute(
                    "SELECT id, created_at, merged_into, created_seq FROM stories "
                    "ORDER BY created_seq DESC LIMIT ?",
                    (limit + 1,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, created_at, merged_into, created_seq FROM stories "
                    "WHERE created_seq < ? ORDER BY created_seq DESC LIMIT ?",
                    (cursor, limit + 1),
                ).fetchall()
        kept = rows[:limit]
        headers = [_decoded(_header_from, row) for row in kept]
        more = len(rows) > limit
        return _decoded(
            lambda: StoryPage(stories=tuple(headers), next_cursor=kept[-1][3] if more else None)
        )

    async def stories_of(self, member: StoryMember) -> tuple[StoryHeader, ...]:
        """Read the stories ``member`` belongs to directly, newest first (ADR-0289 §3)."""
        (named,) = story_members((member,))
        return await self._locked(self._stories_of_sync, named)

    def _stories_of_sync(self, member: StoryMember) -> tuple[StoryHeader, ...]:
        with self._transaction("read a member's stories", immediate=False) as conn:
            rows = conn.execute(
                "SELECT s.id, s.created_at, s.merged_into FROM members m "
                "JOIN stories s ON s.id = m.story_id "
                "WHERE m.kind = ? AND m.member_id = ? ORDER BY s.created_seq DESC",
                (member.kind.value, member.id),
            ).fetchall()
        return tuple(_decoded(_header_from, row) for row in rows)

    # --- the page: reads (ADR-0300 §3) ---------------------------------------

    async def current_page(self, story_id: Identifier) -> StoryPageState | None:
        """Read a story's current page with the notes and episodes pending on it."""
        target = _checked_id(story_id)
        return await self._locked(self._current_page_sync, target)

    def _current_page_sync(self, story_id: str) -> StoryPageState | None:
        with self._transaction("read a story's page", immediate=False) as conn:
            header = self._header(conn, story_id)
            if header is None:
                return None
            as_of = self._ticks(conn)
            page_row = conn.execute(
                "SELECT version, written_at, lines, outside FROM pages WHERE story_id = ?",
                (story_id,),
            ).fetchone()
            note_rows = conn.execute(
                "SELECT id, text, author, written_during, outside, written_at FROM notes "
                "WHERE story_id = ? AND pending_since IS NOT NULL ORDER BY id",
                (story_id,),
            ).fetchall()
            episode_rows = conn.execute(
                "SELECT member_id FROM members WHERE story_id = ? AND kind = ? "
                "AND pending_since IS NOT NULL ORDER BY position",
                (story_id, _ACTIVATION),
            ).fetchall()
        page = None if page_row is None else _decoded(_page_from, page_row)
        notes = tuple(_decoded(_note_from, row) for row in note_rows)
        return _decoded(
            lambda: StoryPageState(
                story=header,
                page=page,
                pending_notes=notes,
                pending_episodes=tuple(row[0] for row in episode_rows),
                as_of=as_of,
            )
        )

    async def notes(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryNoteList | None:
        """Read a page of the notes a story holds, in the order they were written."""
        target = _checked_id(story_id)
        check_story_page(cursor, limit)
        return await self._locked(self._notes_sync, target, cursor, limit)

    def _notes_sync(self, story_id: str, cursor: int | None, limit: int) -> StoryNoteList | None:
        with self._transaction("read a story's notes", immediate=False) as conn:
            header = self._header(conn, story_id)
            if header is None:
                return None
            rows = conn.execute(
                "SELECT id, text, author, written_during, outside, written_at FROM notes "
                "WHERE story_id = ? AND id > ? "
                "ORDER BY id LIMIT ?",
                (story_id, -1 if cursor is None else cursor, limit + 1),
            ).fetchall()
        notes = [_decoded(_note_from, row) for row in rows[:limit]]
        more = len(rows) > limit
        return _decoded(
            lambda: StoryNoteList(
                story=header,
                notes=tuple(notes),
                next_cursor=notes[-1].note_id if more else None,
            )
        )

    async def page_versions(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryPageVersionList | None:
        """Read a page of a story's version log, oldest first."""
        target = _checked_id(story_id)
        check_story_page(cursor, limit)
        return await self._locked(self._versions_sync, target, cursor, limit)

    def _versions_sync(
        self, story_id: str, cursor: int | None, limit: int
    ) -> StoryPageVersionList | None:
        with self._transaction("read a story's page versions", immediate=False) as conn:
            header = self._header(conn, story_id)
            if header is None:
                return None
            rows = conn.execute(
                "SELECT version, written_at, record FROM versions "
                "WHERE story_id = ? AND version > ? ORDER BY version LIMIT ?",
                (story_id, -1 if cursor is None else cursor, limit + 1),
            ).fetchall()
        versions = [_decoded(_version_from, row) for row in rows[:limit]]
        more = len(rows) > limit
        return _decoded(
            lambda: StoryPageVersionList(
                story=header,
                versions=tuple(versions),
                next_cursor=versions[-1].version if more else None,
            )
        )


def _line_from(row: Sequence[Any]) -> StoryLogLine:
    """Decode one stored log row, a ``decided`` line's flag and outcome included."""
    member = None if row[3] is None and row[4] is None else StoryMember(kind=row[3], id=row[4])
    answers = None if row[9] is None else StoryFlagName.model_validate(_json_from(row[9]))
    return StoryLogLine(
        sequence=row[0],
        story_id=row[1],
        change=row[2],
        member=member,
        other_story=row[5],
        actor=row[6],
        trigger=row[7],
        at=_instant_from(row[8]),
        answers=answers,
        outcome=row[10],
    )


def _header_from(row: Sequence[Any]) -> StoryHeader:
    """Decode a stored story row: id, creation instant, merge target."""
    return StoryHeader(story_id=row[0], created_at=_instant_from(row[1]), merged_into=row[2])


def _member_from(row: Sequence[Any]) -> StoryMember:
    """Decode a stored member's kind and id."""
    return StoryMember(kind=row[0], id=row[1])


def _entry_from(row: Sequence[Any]) -> StoryEntry:
    """Decode one stored clean-view row."""
    return StoryEntry(
        position=row[0],
        member=StoryMember(kind=row[1], id=row[2]),
        linked_at=_instant_from(row[3]),
        actor=row[4],
    )


def _note_from(row: Sequence[Any]) -> StoryNote:
    """Decode one stored note: id, text, author, its activation, mark and instant."""
    return StoryNote(
        note_id=row[0],
        text=row[1],
        author=row[2],
        written_during=row[3],
        outside=_flag_from(row[4]),
        written_at=_instant_from(row[5]),
    )


def _json_from(value: object) -> object:
    """Parse a stored JSON column, reporting one that is not JSON text as a ``ValueError``."""
    if type(value) is not str:
        msg = f"a stored story record is not JSON text: {describe_untrusted(value)}"
        raise ValueError(msg)
    return json.loads(value)


def _page_from(row: Sequence[Any]) -> StoryCurrentPage:
    """Decode a stored current page: its version, instant, lines and mark."""
    return StoryCurrentPage.model_validate(
        {
            "version": row[0],
            "written_at": _instant_from(row[1]),
            "lines": _json_from(row[2]),
            "outside": _flag_from(row[3]),
        }
    )


def _version_from(row: Sequence[Any]) -> StoryPageVersion:
    """Decode one stored version: its number, instant and identity record."""
    record = _json_from(row[2])
    if not isinstance(record, dict):
        msg = "a stored page version is not a record"
        raise ValueError(msg)
    return StoryPageVersion.model_validate(
        {**record, "version": row[0], "written_at": _instant_from(row[1])}
    )
