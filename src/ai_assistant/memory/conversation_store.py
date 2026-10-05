"""A persistent :class:`~ai_assistant.core.protocols.ConversationStore` on SQLite.

Local-first storage (ADR-0002) for ADR-0074's conversation record: the durable
identity of a conversation and the delivery rows ADR-0283 §6 keeps beside it. It
holds no history — a conversation's turns are the episodes on its channel in the
``MemoryStore`` (ADR-0283 §1, §4) — so this store
needs no embedder and no vector table, which is the whole of why it is a second
store rather than a widening of the first (ADR-0074 §9).

**Why this module lives in `memory/` while its contract does not.** ADR-0074 §9
rules that ``ConversationStore`` is its *own* Protocol and not an extension of
``MemoryStore``, and that separation is intact: the contract is a distinct
Protocol exchanging distinct types, and neither store holds the other. What is
shared is a package, because the architecture map (`CLAUDE.md`) names no
``conversations`` subsystem, and inventing one is an architecture decision owed
its own ADR rather than a side effect of an implementation lane. Placing the file
beside ``sqlite_store.py`` also keeps this change inside one subsystem. Nothing
here imports the memory store, and nothing in the memory store imports this.

The database file is created with owner-only permissions (ADR-0004 §4). Every
mutation runs inside one ``BEGIN IMMEDIATE`` transaction, which is how the
per-conversation exclusion ADR-0074 §8 puts on the *seam* holds across processes
as well as across coroutines — a lock inside one engine would not.

**A delivery row cannot name a conversation that does not exist** (#452).
``deliveries`` carries a foreign key to ``conversations`` with ``ON DELETE
CASCADE``, and enforcement is switched on for the connection at open — ``PRAGMA
foreign_keys`` is off by default and is *per connection*, so it has to be. The only
``INSERT`` into ``deliveries`` already proves the parent exists inside the same
``IMMEDIATE`` transaction, so the constraint is there for a writer that is not this
module; and :meth:`SqliteConversationStore.drop_if_eligible` deletes the rows
*explicitly* before the record rather than leaning on the cascade — see the
comment there for why the pragma's per-connection scope makes that the safer of the
two.

**There is no turn table** (ADR-0283 §6, §12). The turn index ADR-0074 gave this
store is retired: nothing here creates, reads or writes one. ADR-0283 §12 moves the
hub to a fresh data directory with no migration, so the schema simply lacks it; a
file written by an interim build of the same format that still carries a ``turns``
table is opened without the table being read, and its foreign key cascades away
with each conversation that is dropped.

**The chat space is five more tables** (ADR-0293 §3, §5, §6): ``messages`` (each
conversation's transcript; a deleted message keeps its row as its marker, its text
and every property but its id cleared), ``chat_devices`` ("my devices"),
``conversation_devices``, ``chat_changes`` (the change stream, numbered by an
``AUTOINCREMENT`` key, so a number is never reused even once its row is removed) and
``taken_in`` (the reader's bookkeeping). They are created with ``IF NOT EXISTS``,
so a file of this format written before them is brought forward on open with every
existing conversation's transcript empty; the episode-record format marker does not
move, because no existing row changes shape. Every write to them, and the change it
records, is in the one ``IMMEDIATE`` transaction of the act that makes it.

**There is no observation watermark** (ADR-0285 §4). The schema creates no
``observed_through`` column and nothing adds one to an existing file. Nothing drops
it either: a file written by an earlier build that still carries the column is
opened and served unchanged, because no statement here names it — every read
selects its columns by name, and the one ``INSERT`` names the columns it writes, so
the nullable column takes ``NULL`` on every new row.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
import threading
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    ConversationStoreError,
    IncompatibleStateError,
    MemoryStoreError,
    UnknownConversationError,
)
from ai_assistant.core.types import (
    ChatChanges,
    ChatDevice,
    Conversation,
    ConversationDeletedChange,
    ConversationExport,
    ConversationStartedChange,
    DeletedMessage,
    DevicesChangedChange,
    Identifier,
    MessageAddedChange,
    MessageAuthor,
    MessageDeletedChange,
    MessageReceipt,
    SendOutcome,
    SpokenDelivery,
    SpokenDeliveryState,
    TranscriptMessage,
    TranscriptPage,
    UtcInstant,
    checked_chat_devices,
    describe_untrusted,
)
from ai_assistant.memory._episode_format import (
    EPISODE_RECORD_FORMAT,
    check_format,
    inspect_existing,
)
from ai_assistant.memory._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from contextlib import AbstractContextManager

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import ChatChange, NewMessage

_OWNER_ONLY = 0o600

#: The sidecars SQLite may keep beside a database file. Each holds the same pages
#: the database does, so ADR-0004 §4 reaches them too. SQLite copies the database
#: file's mode onto a sidecar **it creates**, which is what makes restricting the
#: file before the first statement sufficient for those — but that inheritance does
#: not reach one that is *already there*: a ``-journal`` left behind by a crash, or
#: a ``-wal``/``-shm`` from a process that put this file into WAL mode, keeps its
#: own mode across a reopen and then takes Tier 1 pages (#490).
_SIDECARS = ("-journal", "-wal", "-shm")

#: One past the largest value a paging argument accepts: the signed 64-bit ceiling
#: a SQLite bind parameter tops out at (ADR-0073 §2), which this store inherits
#: rather than restates. Duplicated in the canonical fake rather than shared, for
#: the reason ``MemoryStore``'s own bound is: ``ai_assistant.testing`` may not
#: import a subsystem (golden rule 1), and ADR-0074 adds nothing to ``core``.
_PAGE_BOUND = 2**63

#: The default batch :meth:`SqliteConversationStore.stamped_conversation_ids`
#: yields (ADR-0076 §2).
_DEFAULT_PURGE_BATCH = 100

#: The retention horizon an idle conversation is judged against when nobody
#: injects one (ADR-0074 §7). **Finite**: an unbounded default would ship an
#: ever-growing Tier 1 index with no cap decision behind it. ``None`` means "keep
#: forever" and switches reclaim off entirely — the user's deliberate choice.
_DEFAULT_EPISODE_RETENTION = timedelta(days=30)

#: How long a tombstone outlives the deletion that stamped it (ADR-0074 §8):
#: positive and finite, with no ``None`` spelling, because an unbounded grace and
#: a zero one break the deletion protocol in opposite directions.
_DEFAULT_TOMBSTONE_GRACE = timedelta(hours=1)

#: How many times :meth:`SqliteConversationStore.start` re-mints before giving up.
_START_RETRY_BUDGET = 8

#: The most episode ids one :meth:`SqliteConversationStore.deliveries` call takes
#: (ADR-0283 §6:5): ``MemoryStore.channel_episodes``' page bound, so one history page
#: is one call. Duplicated in the canonical fake rather than shared, for
#: :data:`_PAGE_BOUND`'s reason.
_MAX_DELIVERY_IDS: Final = 1000

#: The two arguments :meth:`SqliteConversationStore.record_turn` checks before any
#: I/O through ``core``'s own annotated types, so the store and the fake refuse
#: exactly what a ``core`` model would.
_EPISODE_ID: Final[TypeAdapter[str]] = TypeAdapter(Identifier)
_INSTANT: Final[TypeAdapter[datetime]] = TypeAdapter(UtcInstant)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

#: What a SQLite ``INTEGER`` holds: a signed 64-bit value. A duration beyond it is
#: refused by :func:`_to_micros_of` as this seam's own error rather than left to raise
#: the driver's ``OverflowError``, which is not a ``sqlite3.Error`` and so would cross
#: :meth:`SqliteConversationStore._transaction`'s translation untouched.
_SQLITE_INT_BOUND: Final = 2**63

#: The columns of the ``deliveries`` table (ADR-0283 §6): one row per spoken episode,
#: keyed by the conversation and the episode's id, carrying ADR-0205 §3's fact as
#: three columns rather than one blob — the state as its ``StrEnum`` value, and each
#: duration as a whole number of microseconds, which is ``timedelta``'s own resolution
#: and so exact in both directions. A column per member is what lets a stored row's
#: corruption surface as this seam's own error rather than as a decode of text nobody
#: validated. The state is ``NOT NULL``, because a row exists only where a delivery
#: was recorded and absence is spelled by there being no row; the two durations are
#: nullable, because ``UNKNOWN`` carries neither. The cascading key to
#: ``conversations`` (#452) means a delivery row cannot name a conversation that does
#: not exist. No index beyond the primary key: every read and write names the
#: conversation and the episode together.
_DELIVERIES_COLUMNS: Final = (
    "conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, "
    "episode_id TEXT NOT NULL, delivery_state TEXT NOT NULL, "
    "delivery_played INTEGER, delivery_rendered INTEGER, "
    "PRIMARY KEY(conversation_id, episode_id)"
)

#: ADR-0238 §8's per-conversation search budget: one counter and one flag, on the
#: *conversation* row. **Both are vestigial and both stay** (ADR-0247 §5): the budget
#: is removed, nothing reads either column and nothing writes either one, and the two
#: are kept in the schema so that a database written before that decision and one
#: written after it have **one shape**. No rebuild migration is performed and no column
#: is dropped — SQLite drops a column by rebuilding the table, which is a destructive
#: act over the one table holding every conversation, and the pair costs a deployment
#: two integers per row. ADR-0247 §13 defers the rebuild with what fires it.
#:
#: Held apart from the fresh-database ``CREATE TABLE`` for
#: :meth:`SqliteConversationStore._migrate_search_draw` to add to a file written
#: before them — and the migration stays for the same one-shape reason (§5).
#:
#: **``NOT NULL DEFAULT 0`` on both.** SQLite adds such a column in constant time
#: without rewriting a row, and a build that names only the columns it knows in its
#: ``INSERT INTO conversations(...)`` goes on inserting against the upgraded file —
#: which is what ``start`` now does, because ADR-0247 §5 leaves the pair written by
#: nothing.
_SEARCH_DRAW_COLUMNS: Final = (
    "search_calls INTEGER NOT NULL DEFAULT 0, all_external_user_chosen INTEGER NOT NULL DEFAULT 0"
)

#: The chat space's tables (ADR-0293), created beside the conversation table. A
#: ``messages`` row is a message or, ``deleted = 1``, its marker (§5:12): the marker
#: keeps the position and the device's message id, so a late repeat is still
#: recognised (§4:3), and nothing else. The partial unique index is what makes a
#: device's message id name one message per conversation (§4:2). ``chat_changes`` is
#: numbered by ``AUTOINCREMENT`` so a sequence number is never reused once its row is
#: removed (§5:10); a change row holds no text, and a ``message_added`` row is read
#: with the message it names. Every table but ``chat_changes`` and ``chat_devices``
#: cascades from its conversation, and each is also cleared explicitly where a
#: conversation goes, for the reason ``drop_if_eligible`` gives for the deliveries.
_CHAT_SCHEMA: Final = (
    "CREATE TABLE IF NOT EXISTS messages("
    "conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, "
    "position INTEGER NOT NULL, author TEXT, written_at INTEGER, text TEXT, "
    "replies_to INTEGER, options TEXT, cut_off INTEGER NOT NULL DEFAULT 0, "
    "device_id TEXT, message_id TEXT, deleted INTEGER NOT NULL DEFAULT 0, "
    "PRIMARY KEY(conversation_id, position))",
    "CREATE UNIQUE INDEX IF NOT EXISTS messages_sent "
    "ON messages(conversation_id, device_id, message_id) WHERE device_id IS NOT NULL",
    "CREATE TABLE IF NOT EXISTS chat_devices(device_id TEXT PRIMARY KEY, access TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS conversation_devices("
    "conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, "
    "device_id TEXT NOT NULL, access TEXT NOT NULL, PRIMARY KEY(conversation_id, device_id))",
    "CREATE TABLE IF NOT EXISTS chat_changes("
    "seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, conversation_id TEXT, "
    "position INTEGER, devices TEXT)",
    "CREATE INDEX IF NOT EXISTS chat_changes_conversation ON chat_changes(conversation_id, seq)",
    "CREATE TABLE IF NOT EXISTS taken_in("
    "conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, "
    "position INTEGER NOT NULL, activation_id TEXT NOT NULL, "
    "PRIMARY KEY(conversation_id, position))",
)

#: The most ids or positions one chat-space call takes: the page bound ``deliveries``
#: already sets, for the same one-page-one-call reason. Duplicated in the canonical
#: fake rather than shared, for :data:`_PAGE_BOUND`'s reason.
_MAX_NAMED: Final = 1000

#: The page sizes the chat-space reads default to. The snapshot's is the figure
#: ADR-0293 leaves open (What stays open), chosen here.
_DEFAULT_TRANSCRIPT_PAGE: Final = 50
_DEFAULT_CHANGES_PAGE: Final = 100
_DEFAULT_AWAITING_PAGE: Final = 100

#: The activation id ``take_in`` records goes through ``core``'s identifier type.
_ACTIVATION_ID: Final[TypeAdapter[str]] = TypeAdapter(Identifier)

# **The five columns every conversation read selects.** An ordinary comment and not
# a ``#:`` attribute block, because there is deliberately no name here to attach one
# to: the list is written out at each read that needs it, because ruff's ``S608`` reads
# a query assembled from a name as a possible injection vector whatever the name
# holds, and a literal at the call site is the cheaper answer than a suppression on
# each of them. What keeps the reads in step is
# ``SqliteConversationStore._decode_conversation``, which every one of them feeds.


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes (ADR-0054).

    The store serialises one ``sqlite3`` connection behind an :class:`asyncio.Lock`
    and runs the SQL in a worker thread. A thread cannot be interrupted, so if the
    awaiting coroutine were simply cancelled the enclosing ``async with self._lock``
    would unwind and release the lock **while the worker was still using the
    connection** — letting a second caller use the same connection concurrently,
    which SQLite refuses.

    Deliberately duplicated from :mod:`ai_assistant.memory.sqlite_store` rather
    than shared. ADR-0060 refuses a common home for this helper precisely so that
    subsystems depend on the *obligation* and not on one way of meeting it, and
    reaching into another module for a private name would be the wrong way to
    spell "the same shape" in any case.

    Every failure the worker sees is relayed, ``BaseException`` included. A
    narrower ``except Exception`` catches nothing when ``fn`` raises outside it, so
    both lists stay empty while ``finally: done.set()`` still fires — and the
    caller is then answered out of an empty ``outcome``, an ``IndexError`` standing
    in for the cause rather than chained to it (#680). Which of the two waits below
    runs decides whether the caller sees that or the real failure, which is why it
    presented as an intermittent fault rather than a reproducible one.

    **The completion wait is submitted at most once** (#697). Absorbing a
    cancellation hands the loop a blocking ``done.wait`` job on the default
    executor; a copy that submits a fresh one per cancellation leaves every earlier
    one running, because nothing can interrupt a thread parked in ``Event.wait``
    before the worker sets it. Repeated cancellation of one blocked call then
    occupies the whole pool, which turns one stalled store operation into a process
    that cannot run any thread work at all. Reusing the future costs a local and
    bounds the helper at two executor jobs however many cancellations arrive.
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
            # The signal is one job, reused: see the docstring.
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


def _random_id() -> str:
    """Mint an opaque, random, device-agnostic conversation id (ADR-0074 §1)."""
    return str(uuid4())


def _to_micros(instant: datetime) -> int:
    """Exact integer microsecond UTC epoch for an aware datetime (issue #289).

    Integer arithmetic rather than ``datetime.timestamp()``: an IEEE-754 double's
    53-bit mantissa cannot resolve microseconds near the far end of the datetime
    range, and every deadline this store compares — a retention horizon, a
    tombstone grace — has to stay exact there.
    """
    delta = instant - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _instant_from(value: object, *, what: str) -> datetime:
    """Rebuild the aware UTC instant a stored microsecond epoch encodes.

    **An exact ``int`` is required, and that is the point.** SQLite's ``INTEGER``
    affinity is a preference rather than a constraint: a ``REAL`` that is not
    losslessly integral stays a ``REAL`` in the column, and ``timedelta`` would
    silently *round* one into a plausible instant — so a corrupt value would read
    back as data instead of as the corruption it is. ``bool`` is an ``int``
    subclass and is refused with it, since ``True`` is not an epoch.

    Raises:
        ConversationStoreError: If the stored value is not an exact integer, or
            is outside the representable datetime range. Both are store faults,
            and the contract owes this seam's error for a store fault rather than
            a raw ``OverflowError`` from the arithmetic.
    """
    if type(value) is not int:
        msg = f"a stored {what} is not an integer epoch: {describe_untrusted(value)}"
        raise ConversationStoreError(msg)
    try:
        return _EPOCH + timedelta(microseconds=value)
    except (OverflowError, ValueError) as exc:
        msg = f"a stored {what} is out of range: {describe_untrusted(value)}"
        raise ConversationStoreError(msg) from exc


def _episode_id_of(value: object) -> str:
    """Read a stored episode id, refusing anything that is not a usable identifier.

    :meth:`SqliteConversationStore.deliveries` keys its answer by this value and
    reaches no frozen type whose ``Identifier`` would refuse a corrupt one first, so
    it makes the check itself: coercing a ``BLOB`` with ``str()`` would yield a
    plausible-looking ``"b'...'"`` key that names no episode the caller asked about.

    Raises:
        ConversationStoreError: If the stored value is not a non-blank ``str``.
    """
    if type(value) is not str or not value.strip():
        msg = f"a stored episode id is not usable: {describe_untrusted(value)}"
        raise ConversationStoreError(msg)
    return value


def _stamped_id_of(value: object) -> str:
    """Read a stored conversation id, refusing anything that is not usable.

    The sibling of :func:`_episode_id_of`, and needed for the same reason:
    :meth:`SqliteConversationStore.stamped_conversation_ids` hands its result
    straight to a caller that will act on it, and it reaches no frozen type whose
    ``Identifier`` would refuse a ``BLOB`` or a stray number first. Coercing one
    with ``str()`` would send a sweep after an id nothing holds — and, worse, place
    the *next* batch's lexical cursor after a string no row ever carried, silently
    skipping every tombstone between the two.

    Raises:
        ConversationStoreError: If the stored value is not a non-blank ``str``.
    """
    if type(value) is not str or not value.strip():
        msg = f"a stored conversation id is not usable: {describe_untrusted(value)}"
        raise ConversationStoreError(msg)
    return value


def _delivery_from(state: object, played: object, rendered: object) -> SpokenDelivery | None:
    """Rebuild ADR-0205 §3's fact from its three columns, or report there is none.

    ``NULL`` in ``delivery_state`` is reported as **absence** and not as a state;
    the column is ``NOT NULL``, so :meth:`SqliteConversationStore._decode_delivery`
    reads that answer as the corruption it is. The two durations are read only where
    a state is present, so a stray microsecond beside a ``NULL`` state cannot conjure
    a delivery out of half a row.

    The partition itself is not re-checked here. :class:`SpokenDelivery`'s validator
    owns it and a row that breaches it raises ``ValidationError``, which
    :meth:`SqliteConversationStore._decode_delivery` translates into this seam's
    corrupt-row error — one rule, in the one place ADR-0205 §2 puts it.

    Raises:
        ConversationStoreError: If ``state`` is a string this build's vocabulary does
            not name, which is a stored row no validator further along can place.
    """
    if state is None:
        return None
    try:
        member = SpokenDeliveryState(str(state))
    except ValueError as exc:
        msg = f"a stored delivery carries an unknown state: {describe_untrusted(state)}"
        raise ConversationStoreError(msg) from exc
    return SpokenDelivery(
        state=member,
        played=None if played is None else timedelta(microseconds=_micros_of(played)),
        rendered=None if rendered is None else timedelta(microseconds=_micros_of(rendered)),
    )


def _refuse_unknown_delivery(delivery: SpokenDelivery) -> None:
    """Refuse an ``UNKNOWN`` report before any I/O (ADR-0205 §3).

    ``UNKNOWN`` is written by capture and only through ``record_turn``; it is not a value
    ``record_delivery`` carries. Without this a consumer holding the Protocol could
    stamp ``UNKNOWN`` over ``UNKNOWN`` — a write the row's own state cannot
    distinguish from no write, leaving the row eligible afterwards — and ADR-0205
    §1's stamped-once rule would be a promise the store could not keep against a
    caller that is not the engine.

    Raises:
        ValueError: If the delivery's state is ``UNKNOWN``.
    """
    if delivery.state is SpokenDeliveryState.UNKNOWN:
        msg = (
            "record_delivery does not carry an UNKNOWN delivery: that value is written "
            "by capture through record_turn, and a device that does not know reports "
            "nothing (ADR-0205 §2, §3)"
        )
        raise ValueError(msg)


def _checked_turn(
    episode_id: object, occurred_at: object, delivery: SpokenDelivery | None
) -> tuple[str, datetime]:
    """Check ``record_turn``'s arguments before any I/O (ADR-0283 §6:3).

    The delivery first, because its refusal is the one ADR-0283 names: capture writes
    ``UNKNOWN`` and nothing else, and a device's report reaches a row only through
    ``record_delivery`` and its stamped-once rule. The id and the instant go through
    ``core``'s own annotated types, so a naive or indeterminate instant is refused
    rather than localised to the host's zone (ADR-0023 §3), and a blank id is refused
    rather than written as a key nothing will ever name.

    Returns:
        The episode id and the instant, as ``core`` normalises them.

    Raises:
        ValueError: If ``delivery`` is given and is not ``UNKNOWN``, ``episode_id``
            is not a non-blank ``str``, or ``occurred_at`` is not an aware instant.
    """
    if delivery is not None and delivery.state is not SpokenDeliveryState.UNKNOWN:
        msg = (
            f"record_turn writes only an UNKNOWN delivery, got {delivery.state.value}: "
            f"a device's report reaches a row through record_delivery (ADR-0283 §6:3)"
        )
        raise ValueError(msg)
    try:
        checked_id = _EPISODE_ID.validate_python(episode_id, strict=True)
    except ValidationError as exc:
        msg = f"episode_id must be a non-blank str, got {describe_untrusted(episode_id)}"
        raise ValueError(msg) from exc
    try:
        checked_at = _INSTANT.validate_python(occurred_at, strict=True)
    except ValidationError as exc:
        msg = (
            f"occurred_at must be a timezone-aware instant with a determinate offset, "
            f"got {describe_untrusted(occurred_at)}"
        )
        raise ValueError(msg) from exc
    return checked_id, checked_at


def _checked_episode_ids(episode_ids: object) -> list[str]:
    """Check ``deliveries``' ids before any I/O (ADR-0283 §6:5).

    A bare ``str`` is a ``Sequence[str]`` to the type checker and would be read as its
    characters, so it is refused by name. Each element must be a ``str``, because the
    ids reach SQL as one JSON array and a stray number would match nothing silently.

    Returns:
        The ids, as a list in the order given.

    Raises:
        ValueError: If ``episode_ids`` is a ``str`` or not a sequence, holds more than
            :data:`_MAX_DELIVERY_IDS` ids, or holds an element that is not a ``str``.
    """
    if isinstance(episode_ids, (str, bytes)) or not isinstance(episode_ids, Sequence):
        msg = f"episode_ids must be a sequence of str, got {describe_untrusted(episode_ids)}"
        raise ValueError(msg)
    ids = list(episode_ids)
    if len(ids) > _MAX_DELIVERY_IDS:
        msg = f"episode_ids holds {len(ids)} ids; at most {_MAX_DELIVERY_IDS} are read at once"
        raise ValueError(msg)
    for one in ids:
        if type(one) is not str:
            msg = f"episode_ids holds an id that is not a str: {describe_untrusted(one)}"
            raise ValueError(msg)
    return ids


def _delivery_row(delivery: SpokenDelivery | None) -> tuple[Any, Any, Any]:
    """Render ADR-0205 §3's fact into the three columns, or three nulls.

    The inverse of :func:`_delivery_from`, written beside it so the two spellings of
    one encoding cannot drift. Microseconds because that is ``timedelta``'s own
    resolution, so the value read back is the value written.
    """
    if delivery is None:
        return (None, None, None)
    return (
        delivery.state.value,
        None if delivery.played is None else _to_micros_of(delivery.played),
        None if delivery.rendered is None else _to_micros_of(delivery.rendered),
    )


def _to_micros_of(duration: timedelta) -> int:
    """One duration as a whole number of microseconds, refusing one too large to store.

    **The bound is this backend's, so the refusal is this seam's error** (ADR-0205 §3:
    ``ConversationStoreError`` "where the store cannot be written"). ``timedelta``
    reaches ``timedelta.max`` — about 8.6e19 microseconds — which is a value
    :class:`~ai_assistant.core.types.SpokenDelivery`'s partition happily admits and
    SQLite's signed 64-bit ``INTEGER`` cannot hold. Adversarial review, round 1,
    ``blocker``: without this the driver raises ``OverflowError``, which is **not** a
    ``sqlite3.Error`` and so passes straight through :meth:`_transaction`'s
    translation, out of ``record_delivery``, past
    ``ConversationLifecycle.record_delivery``'s degradation — which catches this seam's
    error and not that one — and costs the owner the turn they had just spoken, for a
    fact about a turn that had already happened.

    Checked before the statement rather than caught after it, so nothing is half
    written and the message names what is wrong rather than relaying a driver's.

    Raises:
        ConversationStoreError: If the duration is outside the range this store can
            hold.
    """
    micros = duration // timedelta(microseconds=1)
    if not -_SQLITE_INT_BOUND <= micros < _SQLITE_INT_BOUND:
        msg = (
            f"a delivery duration of {micros} microseconds is outside the range this "
            f"store can hold, so the episode's delivery was not written (ADR-0205 §3)"
        )
        raise ConversationStoreError(msg)
    return micros


def _micros_of(value: object) -> int:
    """Read one stored duration's microseconds, refusing anything that is not one.

    ``bool`` is excluded with the same care :func:`_instant_from` takes over an
    instant: it is an ``int`` subclass and ``True`` is not a duration.

    Raises:
        ConversationStoreError: If the stored value is not an integer.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"a stored delivery carries a duration that is not an integer: {value!r}"
        raise ConversationStoreError(msg)
    return value


def _check_page_bound(name: str, value: object) -> None:
    """Refuse a paging argument that is not an exact ``int`` in ``[0, 2**63)``.

    ADR-0073 §2's posture, and the check this backend most needs: a negative bound
    would reach SQLite, which reads ``LIMIT -1`` as *no limit at all*, and an
    over-wide one raises ``OverflowError`` out of the driver.

    **The type is part of the range**, because "a signed 64-bit integer" is what
    the rule is about and the two backends disagree without it: ``LIMIT 1.5``
    reaches SQLite as a datatype error while an in-memory store slices a list and
    raises ``TypeError``. Two stores disagreeing about a bad argument is exactly
    the failure ADR-0073 §2 exists to stop. ``bool`` is refused with the rest —
    it is an ``int`` subclass, and ``limit=True`` is not a page size.

    Raises:
        ValueError: If ``value`` is not an ``int``, is negative, or is beyond the
            signed 64-bit range.
    """
    if type(value) is not int or not 0 <= value < _PAGE_BOUND:
        msg = f"{name} must be an int in [0, 2**63), got {describe_untrusted(value)}"
        raise ValueError(msg)


def _check_position(name: str, value: object) -> int:
    """Refuse a position that is not an exact ``int`` in ``[1, 2**63)``.

    ``bool`` is refused with the rest: ``True`` is not a position.

    Raises:
        ValueError: If ``value`` is not such an ``int``.
    """
    if type(value) is not int or not 1 <= value < _PAGE_BOUND:
        msg = f"{name} must be an int in [1, 2**63), got {describe_untrusted(value)}"
        raise ValueError(msg)
    return value


def _checked_positions(positions: object) -> tuple[int, ...]:
    """Check a sequence of positions once, before any I/O (ADR-0065).

    Raises:
        ValueError: If ``positions`` is a ``str`` or not a sequence, holds more than
            :data:`_MAX_NAMED`, or holds a value that is not a position.
    """
    if isinstance(positions, (str, bytes)) or not isinstance(positions, Sequence):
        msg = f"positions must be a sequence of int, got {describe_untrusted(positions)}"
        raise ValueError(msg)
    held = tuple(positions)
    if len(held) > _MAX_NAMED:
        msg = f"positions holds {len(held)}; at most {_MAX_NAMED} are named at once"
        raise ValueError(msg)
    for one in held:
        _check_position("a position", one)
    return held


def _checked_conversation_ids(conversation_ids: object) -> tuple[str, ...] | None:
    """Check ``changes``' restriction once, before any I/O (ADR-0065).

    Raises:
        ValueError: If ``conversation_ids`` is a ``str`` or not a sequence, holds more
            than :data:`_MAX_NAMED` ids, or holds an element that is not a ``str``.
    """
    if conversation_ids is None:
        return None
    if isinstance(conversation_ids, (str, bytes)) or not isinstance(conversation_ids, Sequence):
        described = describe_untrusted(conversation_ids)
        msg = f"conversation_ids must be a sequence of str, got {described}"
        raise ValueError(msg)
    held = tuple(conversation_ids)
    if len(held) > _MAX_NAMED:
        msg = f"conversation_ids holds {len(held)}; at most {_MAX_NAMED} are named at once"
        raise ValueError(msg)
    for one in held:
        if type(one) is not str:
            msg = f"conversation_ids holds an id that is not a str: {describe_untrusted(one)}"
            raise ValueError(msg)
    return held


def _checked_activation_id(activation_id: object) -> str:
    """Check ``take_in``'s activation through ``core``'s own identifier type.

    Raises:
        ValueError: If ``activation_id`` is not a non-blank ``str``.
    """
    try:
        return _ACTIVATION_ID.validate_python(activation_id, strict=True)
    except ValidationError as exc:
        msg = f"activation_id must be a non-blank str, got {describe_untrusted(activation_id)}"
        raise ValueError(msg) from exc


def _check_stored_position(value: object) -> int:
    """Read a stored position, refusing anything that is not one.

    Raises:
        ConversationStoreError: If the stored value is not an ``int`` of at least 1.
    """
    if type(value) is not int or value < 1:
        msg = f"a stored position is not usable: {describe_untrusted(value)}"
        raise ConversationStoreError(msg)
    return value


def _checked_stored_activation(value: object) -> str:
    """Read a stored activation id, refusing anything that is not a usable identifier.

    Raises:
        ConversationStoreError: If the stored value is not a non-blank ``str``.
    """
    if type(value) is not str or not value.strip():
        msg = f"a stored activation id is not usable: {describe_untrusted(value)}"
        raise ConversationStoreError(msg)
    return value


def _devices_json(devices: tuple[ChatDevice, ...]) -> str:
    """Render a set of devices as the JSON a change row holds."""
    return json.dumps([one.model_dump(mode="json") for one in devices])


def _json_list_of(value: object) -> list[object]:
    """Decode a stored JSON array, refusing any other stored shape.

    The container is checked as well as the text: a stored ``"yes"`` is valid JSON
    that ``tuple()`` would read as three one-letter options, and a stored ``{}``
    one that iterates as nothing, so either would read back as plausible data.

    Raises:
        TypeError: If the stored value is not text, or does not decode to an array.
        ValueError: If the stored text is not JSON.
    """
    if type(value) is not str:
        raise TypeError(describe_untrusted(value))
    decoded = json.loads(value)
    if type(decoded) is not list:
        msg = f"a stored JSON value is not an array: {describe_untrusted(value)}"
        raise TypeError(msg)
    return decoded


def _devices_from(conversation_id: object, value: object) -> tuple[ChatDevice, ...]:
    """Rebuild a change row's set of devices, surfacing corruption as this seam's error.

    Raises:
        ConversationStoreError: If the stored value is not a JSON list of devices.
    """
    try:
        decoded = _json_list_of(value)
        return checked_chat_devices([ChatDevice.model_validate(one) for one in decoded])
    except (ValueError, TypeError) as exc:
        described = describe_untrusted(conversation_id)
        msg = f"a stored change's devices could not be decoded for {described}"
        raise ConversationStoreError(msg) from exc


def _bool_of(value: object) -> bool:
    """Read a stored ``0``/``1`` flag, refusing anything else.

    Raises:
        ConversationStoreError: If the stored value is not exactly ``0`` or ``1``.
    """
    if type(value) is not int or value not in {0, 1}:
        msg = f"a stored flag is not 0 or 1: {describe_untrusted(value)}"
        raise ConversationStoreError(msg)
    return bool(value)


def _message_from(row: Sequence[Any]) -> TranscriptMessage | DeletedMessage:
    """Rebuild a message, or its marker, from the message columns.

    The columns are ``conversation_id, position, author, written_at, text,
    replies_to, options, cut_off, device_id, message_id, deleted``.

    Raises:
        ConversationStoreError: If the stored row does not decode.
    """
    try:
        if _bool_of(row[10]):
            return DeletedMessage(conversation_id=row[0], position=row[1])
        options = _json_list_of(row[6])
        return TranscriptMessage(
            conversation_id=row[0],
            position=row[1],
            written_at=_instant_from(row[3], what="written_at"),
            author=MessageAuthor(str(row[2])),
            text=row[4],
            replies_to=row[5],
            options=cast("tuple[str, ...]", tuple(options)),  # validated by the model
            cut_off=_bool_of(row[7]),
            device_id=row[8],
            message_id=row[9],
        )
    except (ValidationError, ValueError, TypeError, OverflowError) as exc:
        msg = f"a stored message could not be decoded: {exc}"
        raise ConversationStoreError(msg) from exc


def _change_from(row: Sequence[Any]) -> ChatChange:
    """Rebuild one change from its row and, for an addition, the message it names.

    The columns are ``seq, kind, conversation_id, position, devices`` and then the
    message columns of the joined row, ``NULL`` where none joined.

    Raises:
        ConversationStoreError: If the stored row does not decode, or an addition
            names a message the transcript does not hold standing.
    """
    seq, kind, conversation_id = row[0], row[1], row[2]
    try:
        if kind == "message_added":
            message = _message_from(row[5:])
            if not isinstance(message, TranscriptMessage):
                msg = "an addition names a message that was deleted"
                raise ConversationStoreError(msg)
            return MessageAddedChange(seq=seq, message=message)
        if kind == "message_deleted":
            marker = DeletedMessage(conversation_id=conversation_id, position=row[3])
            return MessageDeletedChange(seq=seq, marker=marker)
        if kind == "conversation_started":
            return ConversationStartedChange(
                seq=seq,
                conversation_id=conversation_id,
                devices=_devices_from(conversation_id, row[4]),
            )
        if kind == "conversation_deleted":
            return ConversationDeletedChange(seq=seq, conversation_id=conversation_id)
        if kind == "devices_changed":
            return DevicesChangedChange(
                seq=seq,
                conversation_id=conversation_id,
                devices=_devices_from(conversation_id, row[4]),
            )
    except ConversationStoreError:
        raise
    except (ValidationError, ValueError, TypeError) as exc:
        msg = f"a stored change could not be decoded: {exc}"
        raise ConversationStoreError(msg) from exc
    msg = f"a stored change carries an unknown kind: {describe_untrusted(kind)}"
    raise ConversationStoreError(msg)


class SqliteConversationStore:
    """A persistent ``ConversationStore`` backed by ``sqlite3``."""

    def __init__(  # noqa: PLR0913 — one keyword per injected seam the contract names
        self,
        *,
        path: Path | str,
        now: Clock = _utcnow,
        new_id: Callable[[], str] = _random_id,
        retention: timedelta | None = _DEFAULT_EPISODE_RETENTION,
        tombstone_grace: timedelta = _DEFAULT_TOMBSTONE_GRACE,
        purge_batch: int = _DEFAULT_PURGE_BATCH,
    ) -> None:
        """Open (or create) the store at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
            now: Clock the store stamps and judges deadlines with; injectable for
                deterministic tests. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, because this seam
                never reaches a `core` field validator — every reading becomes an
                integer microsecond epoch — so the producer is the only place a
                naive or indeterminate reading can be caught (ADR-0026 §7).
            new_id: The injected id factory ``start`` mints through (ADR-0074 §1).
            retention: The horizon an idle conversation is reclaimed against;
                ``None`` disables reclaim entirely (ADR-0074 §7).
            tombstone_grace: How long a stamped conversation's record outlives the
                stamp (ADR-0074 §8).
            purge_batch: The batch size :meth:`stamped_conversation_ids` uses by
                default.

        Raises:
            ValueError: If ``tombstone_grace`` is not strictly positive, if
                ``retention`` is set and not strictly positive, or if the default
                batch size is out of range. The two durations are refused
                rather than clamped for ADR-0074 §8's reason: a zero or negative
                grace and an unbounded one break the deletion protocol in opposite
                directions.
            ConversationStoreError: If the database cannot be opened or prepared.
        """
        # The type is checked before the comparison, because `None <= timedelta(0)`
        # raises `TypeError` and this constructor documents `ValueError` for a
        # duration it will not accept — whatever is wrong with it.
        if not isinstance(tombstone_grace, timedelta) or tombstone_grace <= timedelta(0):
            described = describe_untrusted(tombstone_grace)
            msg = f"tombstone_grace must be a strictly positive timedelta, got {described}"
            raise ValueError(msg)
        if retention is not None and (
            not isinstance(retention, timedelta) or retention <= timedelta(0)
        ):
            described = describe_untrusted(retention)
            msg = f"retention must be a strictly positive timedelta or None, got {described}"
            raise ValueError(msg)
        _check_page_bound("purge_batch", purge_batch)
        self._clock = checked_clock(now, owner="SqliteConversationStore")
        self._new_id = new_id
        self._retention = retention
        self._grace = tombstone_grace
        self._purge_batch = purge_batch
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    # --- opening -------------------------------------------------------------

    def _setup(self) -> sqlite3.Connection:
        """Open the connection and create the schema, or fail with the seam's error."""
        try:
            inspect_existing(self._path)
        except MemoryStoreError as exc:
            raise ConversationStoreError("cannot inspect conversation store format") from exc
        try:
            # `isolation_level=None` puts the driver in autocommit mode, so every
            # transaction below is an explicit `BEGIN ... COMMIT` this module
            # controls. The implicit transactions the driver would otherwise open
            # are *deferred*, upgrading to a write lock only at the first write —
            # which leaves a read-then-write mutation open to exactly the
            # interleaving the exclusion exists to forbid.
            conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        except (sqlite3.Error, OSError, ValueError) as exc:
            # ``ValueError`` is named because a path carrying an embedded NUL
            # raises it out of the driver rather than a ``sqlite3.Error``, and a
            # bad path is this layer's fault to report rather than a raw builtin
            # escaping past the ``ConversationStoreError`` boundary this
            # constructor documents. Doubly so here: the constructor already
            # documents ``ValueError`` for a duration it refuses, so an
            # untranslated one from the path reads as that instead (#1933).
            msg = f"failed to open conversation store at {self._path!r}: {exc}"
            raise ConversationStoreError(msg) from exc
        try:
            # Restricted *before* the first write, not after the schema is built.
            # SQLite copies the database file's mode onto every rollback journal
            # it creates for it, so a journal written while the file still
            # carried the process umask would be world-readable — and an
            # interrupted write leaves that journal on disk holding Tier 1 pages
            # (ADR-0004 §4). `connect` creates the file, so there is something to
            # restrict by the time this runs.
            # Refuse incompatible state before chmod or a write transaction. The
            # format marker is the whole test: the turn table whose shape was
            # probed here is retired (ADR-0283 §6, §12).
            check_format(conn, allow_empty=True)
            self._restrict_permissions()
            conn.execute("BEGIN IMMEDIATE")
            existing_format = check_format(conn, allow_empty=True)
            if not existing_format:
                conn.execute("CREATE TABLE episode_record_format(version INTEGER NOT NULL)")
                conn.execute(
                    "INSERT INTO episode_record_format VALUES (?)", (EPISODE_RECORD_FORMAT,)
                )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS conversations("
                "id TEXT PRIMARY KEY, started_at INTEGER NOT NULL, "
                "last_active_at INTEGER NOT NULL, last_turn_at INTEGER, deleted_at INTEGER, "
                + _SEARCH_DRAW_COLUMNS
                + ")"
            )
            # Straight after the table it belongs to: `CREATE TABLE IF NOT EXISTS` is
            # a no-op against a file that already holds `conversations`, so a
            # database written before ADR-0238 would otherwise fail its first read on
            # two columns that are not there.
            self._migrate_search_draw(conn)
            # ADR-0283 §6's delivery rows. No turn table is created: the index is
            # retired (ADR-0283 §6, §12).
            conn.execute("CREATE TABLE IF NOT EXISTS deliveries(" + _DELIVERIES_COLUMNS + ")")
            # ADR-0293's chat space, beside the conversation it belongs to.
            for statement in _CHAT_SCHEMA:
                conn.execute(statement)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS conversations_activity "
                "ON conversations(last_active_at DESC, id)"
            )
            conn.execute("COMMIT")
            self._set_foreign_keys(conn, enforced=True)
        except MemoryStoreError as exc:
            conn.close()
            raise ConversationStoreError("cannot read conversation record format") from exc
        except ConversationStoreError, IncompatibleStateError:
            conn.close()  # never leak the connection when opening fails
            raise
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to open conversation store at {self._path!r}: {exc}"
            raise ConversationStoreError(msg) from exc
        return conn

    @staticmethod
    def _set_foreign_keys(conn: sqlite3.Connection, *, enforced: bool) -> None:
        """Set foreign key enforcement for this connection, and prove the setting took.

        ``PRAGMA foreign_keys`` is **per connection**, so switching it on here is
        what makes the constraint in :data:`_DELIVERIES_COLUMNS` mean anything at all
        — a schema carrying a key nobody enforces is documentation.

        Reading the setting back is the point of the method rather than a flourish:
        the statement is a **silent no-op** in a build compiled with
        ``SQLITE_OMIT_FOREIGN_KEY`` and inside an open transaction alike, and either
        way the store would go on believing something about a setting it had not
        changed. The call is issued at open, where nothing has begun one.

        A build that omits foreign keys altogether reads back ``0`` whatever is
        asked of it, so it fails the ``enforced=True`` call — loudly, at
        construction, which is where to discover that this store cannot keep its
        own invariant. ``enforced=False`` is kept for a caller that must copy rows
        the constraint would refuse; nothing in this module is one today.

        Raises:
            ConversationStoreError: If the setting did not take.
        """
        statement, wanted = (
            ("PRAGMA foreign_keys = ON", 1)
            if enforced
            else (
                "PRAGMA foreign_keys = OFF",
                0,
            )
        )
        conn.execute(statement)
        reading = conn.execute("PRAGMA foreign_keys").fetchone()
        if not reading or reading[0] != wanted:
            msg = (
                "this SQLite build does not enforce foreign keys, so a delivery row could "
                "not be kept from naming a conversation that does not exist"
                if enforced
                else "foreign key enforcement could not be switched off for the schema rebuild"
            )
            raise ConversationStoreError(msg)

    @staticmethod
    def _migrate_search_draw(conn: sqlite3.Connection) -> None:
        """Add ADR-0238 §8's counter and flag to a ``conversations`` table without them.

        **It stays although nothing reads either column** (ADR-0247 §5). What it buys
        is one shape: a file written before ADR-0238, one written under it and one
        written after the budget's removal all hold the same ``conversations`` table,
        so no read, export or backup has to know which of the three it is looking at.
        Dropping the pair instead would mean rebuilding the one table holding every
        conversation, which ADR-0247 §13 defers with what fires it.

        ``NOT NULL DEFAULT 0`` on both is what makes it free — SQLite adds the columns
        in constant time **without rewriting a row**, and no existing column changes.
        **Nothing back-fills either one** (ADR-0247 §10): no inference, repair or
        reconstruction is performed on any row, and a conversation whose flag reads
        ``0`` behaves exactly as one whose flag reads ``1``, because neither is read.

        An ``ALTER TABLE ... ADD COLUMN`` rather than a rebuild, because that is the
        whole of what is owed. ``PRAGMA table_info`` is read rather than the stored DDL
        text, because what decides is the shape the table actually has. Each column is
        checked on its own, so a file interrupted between the two ``ALTER`` statements
        is brought forward rather than left half-migrated.
        """
        present = {str(row[1]) for row in conn.execute("PRAGMA table_info(conversations)")}
        for column in _SEARCH_DRAW_COLUMNS.split(", "):
            if column.split(" ")[0] not in present:
                conn.execute("ALTER TABLE conversations ADD COLUMN " + column)

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case rather than a fault — :data:`_SIDECARS`
        names every file SQLite *may* keep, and a cleanly closed database has none of
        them — so absence is tolerated one name at a time. Nothing else is: a sidecar
        this process cannot restrict is a Tier 1 file it is about to write through, so
        that failure propagates and the open fails.

        A *symlink* under a sidecar's name is skipped rather than followed. ``chmod``
        follows links, and ``os.chmod(follow_symlinks=False)`` is unsupported on
        Linux, so restricting one would silently narrow a file that holds none of
        this store's data and that this store has no business modifying.

        Skipping it strands no page anywhere this method could not reach, because
        SQLite does not follow such a link either (verified against 3.53.1, and
        asserted in the conversation store's tests): a symlinked ``-journal`` is not
        a hot journal, so SQLite unlinks *the link* at the first statement and writes
        a real file in its place — which inherits the ``0600`` set just above — and a
        symlinked ``-wal`` on a WAL-mode database is refused outright rather than
        written through. What is left is a check-then-chmod race, and winning it
        needs write access to the database's own directory, which is already past
        ADR-0004 §4 by routes this method could never close.

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

    def _now(self) -> datetime:
        """The guarded clock's reading, as this store's own error (ADR-0026 §4).

        Raises:
            ConversationStoreError: If the reading is naive, indeterminate, or
                outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise ConversationStoreError(str(exc)) from exc

    def _transaction(
        self, what: str, *, immediate: bool = True
    ) -> AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front, so a read-then-write mutation
        cannot interleave with another writer's — which is how the exclusion
        ADR-0074 §8 places on the seam holds **across processes** and not merely
        across coroutines on one loop. ``immediate=False`` is the read form: a
        deferred transaction, so several ``SELECT``s in one block see one
        consistent snapshot rather than two states either side of a racing write.

        Anything other than a backend failure propagates unchanged, after the
        transaction is rolled back, so a refusal raised inside a block leaves
        nothing of that block written.

        Raises:
            ConversationStoreError: If the backend fails at any point.
        """
        return transaction(self._conn, what, error=ConversationStoreError, immediate=immediate)

    @staticmethod
    def _fetch(
        conn: sqlite3.Connection, what: str, sql: str, params: Sequence[object] = ()
    ) -> list[Any]:
        """Run one read on an open connection, translating a backend failure.

        Raises:
            ConversationStoreError: If the store cannot be read.
        """
        try:
            return conn.execute(sql, tuple(params)).fetchall()
        except sqlite3.Error as exc:
            msg = f"failed to {what}: {exc}"
            raise ConversationStoreError(msg) from exc

    @staticmethod
    def _decode_conversation(row: Sequence[Any]) -> Conversation:
        """Rebuild a :class:`Conversation` from its row, surfacing corruption.

        The row is the five columns every conversation read selects, in the order
        each of them names them.

        Raises:
            ConversationStoreError: If the stored row does not validate.
        """
        try:
            return Conversation(
                id=row[0],
                started_at=_instant_from(row[1], what="started_at"),
                last_active_at=_instant_from(row[2], what="last_active_at"),
                last_turn_at=(
                    None if row[3] is None else _instant_from(row[3], what="last_turn_at")
                ),
                deleted_at=None if row[4] is None else _instant_from(row[4], what="deleted_at"),
            )
        except (ValidationError, TypeError, OverflowError) as exc:
            msg = f"a stored conversation could not be decoded: {exc}"
            raise ConversationStoreError(msg) from exc

    @classmethod
    def _row_of(cls, conn: sqlite3.Connection, conversation_id: str) -> Sequence[Any] | None:
        """Read one conversation row inside an open transaction, or ``None``."""
        rows = cls._fetch(
            conn,
            "read a conversation",
            "SELECT c.id, c.started_at, c.last_active_at, c.last_turn_at, c.deleted_at "
            "FROM conversations c WHERE c.id = ?",
            (conversation_id,),
        )
        return rows[0] if rows else None

    @staticmethod
    def _record_change(
        conn: sqlite3.Connection,
        kind: str,
        conversation_id: str | None,
        *,
        position: int | None = None,
        devices: tuple[ChatDevice, ...] | None = None,
    ) -> None:
        """Record one change in the stream, inside the transaction making it (§5:10)."""
        conn.execute(
            "INSERT INTO chat_changes(kind, conversation_id, position, devices) "
            "VALUES (?, ?, ?, ?)",
            (kind, conversation_id, position, None if devices is None else _devices_json(devices)),
        )

    @staticmethod
    def _clear_chat_of(conn: sqlite3.Connection, conversation_id: str) -> None:
        """Delete the transcript, devices, bookkeeping and changes kept under a conversation.

        Explicitly rather than by the cascade, for the reason ``drop_if_eligible``
        gives for the deliveries; the change rows have no key to cascade from.
        """
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute(
            "DELETE FROM conversation_devices WHERE conversation_id = ?", (conversation_id,)
        )
        conn.execute("DELETE FROM taken_in WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM chat_changes WHERE conversation_id = ?", (conversation_id,))

    @classmethod
    def _head(cls, conn: sqlite3.Connection) -> int:
        """The change stream's latest sequence number, ``0`` before the first change.

        Read from ``sqlite_sequence``, which ``AUTOINCREMENT`` keeps, so a number
        whose row was removed still counts.
        """
        rows = cls._fetch(
            conn,
            "read the change stream's head",
            "SELECT seq FROM sqlite_sequence WHERE name = 'chat_changes'",
        )
        if not rows:
            return 0
        head = rows[0][0]
        if type(head) is not int or head < 0:
            msg = f"the change stream's head is corrupt: {describe_untrusted(head)}"
            raise ConversationStoreError(msg)
        return head

    @classmethod
    def _devices_of(
        cls, conn: sqlite3.Connection, conversation_id: str | None
    ) -> tuple[ChatDevice, ...]:
        """Read "my devices" (``None``) or one conversation's devices, ``device_id`` ascending.

        Raises:
            ConversationStoreError: If the store cannot be read, or a row is corrupt.
        """
        if conversation_id is None:
            rows = cls._fetch(
                conn,
                "read my devices",
                "SELECT device_id, access FROM chat_devices ORDER BY device_id ASC",
            )
        else:
            rows = cls._fetch(
                conn,
                "read a conversation's devices",
                "SELECT device_id, access FROM conversation_devices WHERE conversation_id = ? "
                "ORDER BY device_id ASC",
                (conversation_id,),
            )
        try:
            return tuple(ChatDevice(device_id=row[0], access=row[1]) for row in rows)
        except (ValidationError, TypeError) as exc:
            msg = f"a stored device could not be decoded: {exc}"
            raise ConversationStoreError(msg) from exc

    @staticmethod
    def _unknown(conversation_id: str) -> UnknownConversationError:
        """The refusal §1 requires: an id the store does not know is not created.

        The narrow subclass (ADR-0076 §2), so a sweep can tell an id another
        sweeper already finished from a database that is failing.
        """
        described = describe_untrusted(conversation_id)
        return UnknownConversationError(f"no such conversation: {described}")

    # --- the contract --------------------------------------------------------

    async def start(self) -> Conversation:
        """Mint an id, insert the record if that id is absent, and return it.

        The presence check and the insert are one ``IMMEDIATE`` transaction, so a
        second writer cannot land the row between them; a collision re-mints, and
        an exhausted budget raises rather than returning someone else's
        conversation (ADR-0074 §1).

        Raises:
            ConversationStoreError: If the retry budget is exhausted, the id
                factory produced something unusable, or the store cannot be
                written.
        """
        for _ in range(_START_RETRY_BUDGET):
            minted = self._new_id()
            async with self._lock:
                conversation = await _run_to_completion(self._insert_sync, minted)
            if conversation is not None:
                return conversation
        msg = (
            f"could not mint an unused conversation id in {_START_RETRY_BUDGET} attempts; "
            f"the injected id factory is repeating"
        )
        raise ConversationStoreError(msg)

    def _insert_sync(self, minted: str) -> Conversation | None:
        """Insert a conversation under ``minted``, or ``None`` if that id is taken.

        The clock is read **inside** the transaction, after the write exclusion is
        held. A reading taken before it could go stale while this call queues
        behind another writer — or behind a cross-process ``BEGIN IMMEDIATE`` —
        and a conversation would then be created carrying an activity stamp
        already in the past, which the retention reclaim judges against
        (ADR-0074 §2, §7).
        """
        with self._transaction("start a conversation") as conn:
            now = self._now()
            # Validated before it reaches the database, so a misbehaving factory
            # is this seam's error rather than a raw one from a bind parameter.
            try:
                conversation = Conversation(id=minted, started_at=now, last_active_at=now)
            except (ValidationError, TypeError) as exc:
                msg = f"the id factory minted an unusable id: {describe_untrusted(minted)}"
                raise ConversationStoreError(msg) from exc
            if self._row_of(conn, conversation.id) is not None:
                return None
            conn.execute(
                # **Neither vestigial column is named** (ADR-0247 §5). The budget is
                # removed, so `start` no longer creates a draw and the two columns take
                # the `DEFAULT 0` their declaration carries — "read by nothing and
                # written by nothing", which is what makes them costless to keep.
                "INSERT INTO conversations(id, started_at, last_active_at, last_turn_at, "
                "deleted_at) "
                "VALUES (?, ?, ?, NULL, NULL)",
                (
                    conversation.id,
                    _to_micros(conversation.started_at),
                    _to_micros(conversation.last_active_at),
                ),
            )
            # ADR-0293 §2:1, §3:1: empty, on "my devices" as they stand, and the
            # change recorded in the same transaction.
            devices = self._devices_of(conn, None)
            conn.executemany(
                "INSERT INTO conversation_devices(conversation_id, device_id, access) "
                "VALUES (?, ?, ?)",
                [(conversation.id, one.device_id, one.access.value) for one in devices],
            )
            self._record_change(conn, "conversation_started", conversation.id, devices=devices)
            return conversation

    async def get(self, conversation_id: str) -> Conversation | None:
        """Return the conversation, or ``None`` if it is absent or stamped.

        Raises:
            ConversationStoreError: If the store cannot be read, or the stored row
                is corrupt.
        """
        async with self._lock:
            rows = await _run_to_completion(self._get_sync, conversation_id)
        return self._decode_conversation(rows[0]) if rows else None

    def _get_sync(self, conversation_id: str) -> list[Any]:
        return self._fetch(
            self._conn,
            "read a conversation",
            "SELECT c.id, c.started_at, c.last_active_at, c.last_turn_at, c.deleted_at "
            "FROM conversations c WHERE c.id = ? AND c.deleted_at IS NULL",
            (conversation_id,),
        )

    async def mark_active(self, conversation_id: str) -> Conversation:
        """Record that a turn has begun, leaving ``last_turn_at`` alone.

        The clock is read **inside** the exclusion, not before it. A reading taken
        first could go stale while this call queues behind another writer — or
        behind a cross-process ``BEGIN IMMEDIATE`` — and stamp the conversation
        active at an instant that has already passed, which is the reading a
        reclaim then judges against (ADR-0074 §9.4). Matching ``SqliteMemoryStore``,
        whose reads take the same care for the same reason.

        Raises:
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
            ConversationStoreError: If the store cannot be written.
        """
        async with self._lock:
            row = await _run_to_completion(self._mark_active_sync, conversation_id)
        return self._decode_conversation(row)

    def _mark_active_sync(self, conversation_id: str) -> Sequence[Any]:
        with self._transaction("mark a conversation active") as conn:
            now = self._now()
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                raise self._unknown(conversation_id)
            conn.execute(
                "UPDATE conversations SET last_active_at = ? WHERE id = ?",
                (_to_micros(now), conversation_id),
            )
            marked = self._row_of(conn, conversation_id)
            if marked is None:  # pragma: no cover — the row was just updated in this transaction
                raise self._unknown(conversation_id)
            return marked

    async def record_turn(
        self,
        conversation_id: str,
        *,
        episode_id: str,
        occurred_at: datetime,
        delivery: SpokenDelivery | None = None,
    ) -> Conversation | None:
        """Record that a conversational episode landed, under the exclusion (ADR-0283 §6:2).

        The read of the conversation and both writes are one ``IMMEDIATE``
        transaction, so a ``stamp_deleted`` or a ``drop_if_eligible`` lands wholly
        before or wholly after it — which is what lets the writer read a ``None``
        here as "the conversation was gone when the episode landed" (§7:2). The
        delivery row is inserted only where none exists, so a retried capture cannot
        reset a stamped delivery (ADR-0205 §1).

        The argument checks are **before the lock and before any I/O** (§6:3).

        Raises:
            ValueError: If ``delivery`` is not ``UNKNOWN``, ``episode_id`` is blank,
                or ``occurred_at`` is not an aware instant.
            ConversationStoreError: If the store cannot be written.
        """
        checked_id, checked_at = _checked_turn(episode_id, occurred_at, delivery)
        async with self._lock:
            row = await _run_to_completion(
                self._record_turn_sync, conversation_id, checked_id, checked_at, delivery
            )
        return None if row is None else self._decode_conversation(row)

    def _record_turn_sync(
        self,
        conversation_id: str,
        episode_id: str,
        occurred_at: datetime,
        delivery: SpokenDelivery | None,
    ) -> Sequence[Any] | None:
        with self._transaction("record a conversational episode") as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                # Absent or stamped: nothing is written and nothing is raised. The
                # writer reads this as the deletion verification failing (§7:2).
                return None
            conn.execute(
                "UPDATE conversations SET last_turn_at = ? WHERE id = ?",
                (_to_micros(occurred_at), conversation_id),
            )
            if delivery is not None:
                # `OR IGNORE`: a row this conversation already holds for the episode
                # stands as it is, so a retried capture cannot put UNKNOWN back over a
                # stamp (ADR-0205 §1).
                conn.execute(
                    "INSERT OR IGNORE INTO deliveries(conversation_id, episode_id, "
                    "delivery_state, delivery_played, delivery_rendered) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (conversation_id, episode_id, *_delivery_row(delivery)),
                )
            recorded = self._row_of(conn, conversation_id)
            if recorded is None:  # pragma: no cover — the row was just updated here
                return None
            return recorded

    async def record_delivery(
        self, conversation_id: str, *, episode_id: str, delivery: SpokenDelivery
    ) -> bool:
        """Stamp the episode's delivery row if it is still ``UNKNOWN`` (ADR-0283 §6:4).

        The three conditions and the write are one ``IMMEDIATE`` transaction, so two
        reports observing ``UNKNOWN`` cannot both write: the second finds a state that
        is no longer ``UNKNOWN`` and performs nothing, which is ADR-0205 §1's
        stamped-once rule held across processes and not only across coroutines on one
        loop.

        The ``UNKNOWN`` refusal is **before the lock and before any I/O**, on
        ADR-0085 §3's convention for a malformed argument.

        Raises:
            ValueError: If ``delivery.state`` is ``UNKNOWN``.
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
            ConversationStoreError: If the store cannot be written.
        """
        _refuse_unknown_delivery(delivery)
        async with self._lock:
            return await _run_to_completion(
                self._record_delivery_sync, conversation_id, episode_id, delivery
            )

    def _record_delivery_sync(
        self, conversation_id: str, episode_id: str, delivery: SpokenDelivery
    ) -> bool:
        with self._transaction("record an episode's delivery") as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                raise self._unknown(conversation_id)
            # All three of ADR-0205 §3's conditions in one predicate, so the row is
            # written only where every one of them held at the moment of writing —
            # the conversation, the episode, and a recorded state of ``UNKNOWN``. An
            # episode with no row fails the second and is left as it stands: this
            # operation is not a way to give an episode a delivery.
            written = conn.execute(
                "UPDATE deliveries SET delivery_state = ?, delivery_played = ?, "
                "delivery_rendered = ? WHERE conversation_id = ? AND episode_id = ? "
                "AND delivery_state = ?",
                (
                    *_delivery_row(delivery),
                    conversation_id,
                    episode_id,
                    SpokenDeliveryState.UNKNOWN.value,
                ),
            ).rowcount
            return bool(written)

    async def deliveries(
        self, conversation_id: str, *, episode_ids: Sequence[str]
    ) -> Mapping[str, SpokenDelivery]:
        """Return the delivery rows the conversation holds among ``episode_ids``.

        One deferred transaction, so the conversation's liveness and its rows are
        read from one snapshot: a stamp landing between the two cannot leave a
        stamped conversation's rows presented. The ids reach SQL as one JSON array
        read through ``json_each`` rather than as up to a thousand bind parameters,
        so no build's variable limit decides whether a page can be read.

        The argument checks are **before the lock and before any I/O** (§6:5).

        Raises:
            ValueError: If ``episode_ids`` is a ``str``, holds more than 1000 ids, or
                holds an element that is not a ``str``.
            ConversationStoreError: If the store cannot be read, or a stored row is
                corrupt.
        """
        ids = _checked_episode_ids(episode_ids)
        if not ids:
            return {}
        async with self._lock:
            rows = await _run_to_completion(self._deliveries_sync, conversation_id, ids)
        found: dict[str, SpokenDelivery] = {}
        for row in rows:
            delivery = self._decode_delivery(row)
            found[_episode_id_of(row[0])] = delivery
        return found

    def _deliveries_sync(self, conversation_id: str, ids: list[str]) -> list[Any]:
        with self._transaction("read a conversation's deliveries", immediate=False) as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                return []
            return self._fetch(
                conn,
                "read a conversation's deliveries",
                "SELECT episode_id, delivery_state, delivery_played, delivery_rendered "
                "FROM deliveries WHERE conversation_id = ? "
                "AND episode_id IN (SELECT value FROM json_each(?))",
                (conversation_id, json.dumps(ids)),
            )

    @staticmethod
    def _decode_delivery(row: Sequence[Any]) -> SpokenDelivery:
        """Rebuild one delivery row's fact, surfacing corruption as this seam's error.

        The state column is ``NOT NULL`` in the schema, so a ``NULL`` here is a row
        written by something other than this module and is a fault, not an absence:
        absence is spelled by there being no row at all.

        Raises:
            ConversationStoreError: If the stored row does not decode.
        """
        try:
            delivery = _delivery_from(row[1], row[2], row[3])
        except (ValidationError, TypeError, OverflowError) as exc:
            msg = f"a stored delivery could not be decoded: {exc}"
            raise ConversationStoreError(msg) from exc
        if delivery is None:
            msg = f"a stored delivery row carries no state: {describe_untrusted(row[0])}"
            raise ConversationStoreError(msg)
        return delivery

    async def stamped_conversation_ids(
        self,
        *,
        limit: int | None = None,
        after_id: str | None = None,
    ) -> list[str]:
        """Return the next batch of stamped-but-not-dropped ids, ``id`` ascending.

        The cursor is a **lexical bound on the id space** — ``id > ?`` — and never
        a row lookup, because this walk's rows are dropped by the very sweep
        walking them: by the time the caller asks for the next batch, the id it
        carries may name nothing, and a cursor resolved by lookup would stall
        exactly when the sweep was working correctly (ADR-0076 §2). Grace is not a
        filter here; :meth:`drop_if_eligible` judges it under the exclusion.

        Raises:
            ValueError: If ``limit`` is outside ``[0, 2**63)``.
            ConversationStoreError: If the store cannot be read.
        """
        batch = self._purge_batch if limit is None else limit
        _check_page_bound("limit", batch)
        if batch == 0:
            return []
        async with self._lock:
            rows = await _run_to_completion(self._stamped_ids_sync, batch, after_id)
        return [_stamped_id_of(row[0]) for row in rows]

    def _stamped_ids_sync(self, batch: int, after_id: str | None) -> list[Any]:
        if after_id is None:
            return self._fetch(
                self._conn,
                "list stamped conversations",
                "SELECT id FROM conversations WHERE deleted_at IS NOT NULL ORDER BY id ASC LIMIT ?",
                (batch,),
            )
        return self._fetch(
            self._conn,
            "list stamped conversations",
            "SELECT id FROM conversations WHERE deleted_at IS NOT NULL AND id > ? "
            "ORDER BY id ASC LIMIT ?",
            (after_id, batch),
        )

    async def recent(self, *, limit: int = 50, offset: int = 0) -> list[Conversation]:
        """List unstamped conversations, last activity first, ``id`` breaking ties.

        Raises:
            ValueError: If ``limit`` or ``offset`` is outside ``[0, 2**63)``.
            ConversationStoreError: If the store cannot be read.
        """
        _check_page_bound("limit", limit)
        _check_page_bound("offset", offset)
        if limit == 0:
            return []
        async with self._lock:
            rows = await _run_to_completion(self._recent_sync, limit, offset)
        return [self._decode_conversation(row) for row in rows]

    def _recent_sync(self, limit: int, offset: int) -> list[Any]:
        return self._fetch(
            self._conn,
            "list recent conversations",
            "SELECT c.id, c.started_at, c.last_active_at, c.last_turn_at, c.deleted_at "
            "FROM conversations c WHERE c.deleted_at IS NULL "
            "ORDER BY c.last_active_at DESC, c.id ASC LIMIT ? OFFSET ?",
            (limit, offset),
        )

    async def stamp_deleted(self, conversation_id: str) -> bool:
        """Stamp the conversation deleted, returning whether this call did it.

        The clock is read inside the exclusion: a reading taken before it would
        date the tombstone earlier than the stamp actually landed, and the grace
        that outlives the deletion is measured from that instant (ADR-0074 §8).
        """
        async with self._lock:
            return await _run_to_completion(self._stamp_deleted_sync, conversation_id)

    def _stamp_deleted_sync(self, conversation_id: str) -> bool:
        with self._transaction("stamp a conversation deleted") as conn:
            now = self._now()
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                return False
            conn.execute(
                "UPDATE conversations SET deleted_at = ? WHERE id = ?",
                (_to_micros(now), conversation_id),
            )
            # ADR-0293 §2:3: the transcript goes with the conversation, and its
            # devices learn of it from the one change left in the stream.
            self._clear_chat_of(conn, conversation_id)
            self._record_change(conn, "conversation_deleted", conversation_id)
            return True

    async def drop_if_eligible(self, conversation_id: str) -> bool:
        """Remove the record and its delivery rows if still eligible, under the exclusion.

        The eligibility re-check happens *inside* the transaction that drops, which
        is what stops a reclaim destroying a conversation the user has just come
        back to (ADR-0074 §9.4) — and so is the clock reading it is judged
        against, because a reading taken before the exclusion could have gone
        stale while this call queued behind the very continuation that should
        defeat it.
        """
        async with self._lock:
            return await _run_to_completion(self._drop_if_eligible_sync, conversation_id)

    def _drop_if_eligible_sync(self, conversation_id: str) -> bool:
        with self._transaction("drop a conversation") as conn:
            now = self._now()
            row = self._row_of(conn, conversation_id)
            if row is None:
                return False  # nothing to drop; the sweep is idempotent by re-running
            # Decoded through the same guard every read uses, rather than by
            # reaching into the row: a corrupt stamp is a store fault and owes
            # `ConversationStoreError` like any other, and converting a raw epoch
            # here would let an `OverflowError` escape a method the contract
            # documents as returning a bool.
            conversation = self._decode_conversation(row)
            # `now - stamp >= duration` rather than `stamp + duration <= now`:
            # the two are equivalent, but only the first cannot overflow.
            # `checked_clock` admits a reading a day short of `datetime.max`
            # (ADR-0026 §3), and adding a horizon to one raises `OverflowError`
            # out of that same comparison.
            stamped = conversation.deleted_at is not None
            if conversation.deleted_at is not None:
                eligible = now - conversation.deleted_at >= self._grace
            else:
                # ADR-0293 §5:4: reclaim never drops a conversation holding a message.
                eligible = (
                    self._retention is not None
                    and now - conversation.last_active_at >= self._retention
                    and not self._fetch(
                        conn,
                        "read a conversation's transcript",
                        "SELECT 1 FROM messages WHERE conversation_id = ? AND deleted = 0 LIMIT 1",
                        (conversation_id,),
                    )
                )
            if not eligible:
                return False
            # The delivery rows go first and **explicitly** (ADR-0283 §6:7), with
            # ``ON DELETE CASCADE`` behind them as a backstop rather than as the
            # mechanism (#452). ``PRAGMA foreign_keys`` is per connection and off by
            # default, so a cascade this module *relied* on would stop happening on
            # any connection that had not enabled it — and the failure mode is the
            # silent one: every drop would leave rows behind for a conversation
            # minted later under the same id to inherit. Deleting them here makes
            # the drop correct whatever the pragma says; the cascade then only ever
            # fires for a writer that is not this module.
            conn.execute("DELETE FROM deliveries WHERE conversation_id = ?", (conversation_id,))
            if stamped:
                # The stamp cleared the chat and recorded the deletion; what is left
                # is the change that tells devices so, which stays.
                conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
                conn.execute(
                    "DELETE FROM conversation_devices WHERE conversation_id = ?",
                    (conversation_id,),
                )
                conn.execute("DELETE FROM taken_in WHERE conversation_id = ?", (conversation_id,))
            else:
                # A reclaim is a deletion as far as the conversation's devices go.
                self._clear_chat_of(conn, conversation_id)
                self._record_change(conn, "conversation_deleted", conversation_id)
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            return True

    async def export(self) -> ConversationExport:
        """Return the store's own snapshot: its unstamped conversations (ADR-0283 §4:3).

        No liveness filtering — this store cannot ask the ``MemoryStore`` whether a
        conversation's channel still holds an episode (ADR-0074 §9). The clock and
        the rows are read in one deferred transaction.

        Raises:
            ConversationStoreError: If the store cannot be read, or a stored row is
                corrupt.
        """
        async with self._lock:
            exported_at, conversation_rows, message_rows = await _run_to_completion(
                self._export_sync
            )
        conversations = tuple(self._decode_conversation(row) for row in conversation_rows)
        order = {one.id: index for index, one in enumerate(conversations)}
        messages = sorted(
            (_message_from(row) for row in message_rows),
            key=lambda one: (order.get(one.conversation_id, len(order)), one.position),
        )
        try:
            return ConversationExport(
                exported_at=exported_at,
                conversations=conversations,
                messages=tuple(one for one in messages if isinstance(one, TranscriptMessage)),
            )
        except ValidationError as exc:
            msg = f"the stored conversations do not make a consistent export: {exc}"
            raise ConversationStoreError(msg) from exc

    def _export_sync(self) -> tuple[datetime, list[Any], list[Any]]:
        with self._transaction("export conversations", immediate=False) as conn:
            exported_at = self._now()
            conversations = self._fetch(
                conn,
                "export conversations",
                "SELECT c.id, c.started_at, c.last_active_at, c.last_turn_at, c.deleted_at "
                "FROM conversations c WHERE c.deleted_at IS NULL "
                "ORDER BY c.last_active_at DESC, c.id ASC",
            )
            messages = self._fetch(
                conn,
                "export transcripts",
                "SELECT m.conversation_id, m.position, m.author, m.written_at, m.text, "
                "m.replies_to, m.options, m.cut_off, m.device_id, m.message_id, m.deleted "
                "FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                "WHERE c.deleted_at IS NULL AND m.deleted = 0 "
                "ORDER BY m.conversation_id ASC, m.position ASC",
            )
            return exported_at, conversations, messages

    # --- the chat space (ADR-0293) --------------------------------------------

    async def append_message(self, conversation_id: str, message: NewMessage) -> MessageReceipt:
        """Write one message into the transcript, in one ``IMMEDIATE`` transaction.

        The repeat check, the device check, the reply check, the insert and the
        change are one step, so two sends of one message cannot both record it and
        a device removed concurrently either wrote before the removal or not at all.

        Raises:
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
            ConversationStoreError: If the store cannot be written.
        """
        async with self._lock:
            return await _run_to_completion(self._append_message_sync, conversation_id, message)

    def _append_message_sync(self, conversation_id: str, message: NewMessage) -> MessageReceipt:
        with self._transaction("write a message") as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                raise self._unknown(conversation_id)
            if message.author is MessageAuthor.USER:
                sent = self._fetch(
                    conn,
                    "read a sent message",
                    "SELECT position FROM messages WHERE conversation_id = ? "
                    "AND device_id = ? AND message_id = ?",
                    (conversation_id, message.device_id, message.message_id),
                )
                if sent:
                    return MessageReceipt(
                        conversation_id=conversation_id,
                        outcome=SendOutcome.REPEATED,
                        position=sent[0][0],
                    )
                ends = {
                    one.device_id
                    for one in self._devices_of(conn, conversation_id)
                    if one.access.writes
                }
                if message.device_id not in ends:
                    return MessageReceipt(
                        conversation_id=conversation_id, outcome=SendOutcome.NOT_AN_END
                    )
            last = self._fetch(
                conn,
                "read a transcript's last position",
                "SELECT COALESCE(MAX(position), 0) FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )[0][0]
            if type(last) is not int or last < 0:
                msg = f"a stored transcript position is corrupt: {describe_untrusted(last)}"
                raise ConversationStoreError(msg)
            position = last + 1
            if message.replies_to is not None and message.replies_to >= position:
                return MessageReceipt(
                    conversation_id=conversation_id, outcome=SendOutcome.NO_SUCH_REPLY
                )
            try:
                recorded = TranscriptMessage(
                    conversation_id=conversation_id,
                    position=position,
                    written_at=self._now(),
                    **message.model_dump(),
                )
            except ValidationError as exc:
                msg = f"the message could not be placed at position {position}: {exc}"
                raise ConversationStoreError(msg) from exc
            conn.execute(
                "INSERT INTO messages(conversation_id, position, author, written_at, text, "
                "replies_to, options, cut_off, device_id, message_id, deleted) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    conversation_id,
                    position,
                    recorded.author.value,
                    _to_micros(recorded.written_at),
                    recorded.text,
                    recorded.replies_to,
                    json.dumps(list(recorded.options)),
                    int(recorded.cut_off),
                    recorded.device_id,
                    recorded.message_id,
                ),
            )
            self._record_change(conn, "message_added", conversation_id, position=position)
            return MessageReceipt(
                conversation_id=conversation_id, outcome=SendOutcome.RECORDED, position=position
            )

    async def delete_message(self, conversation_id: str, position: int) -> bool:
        """Delete one message, leaving its marker, in one ``IMMEDIATE`` transaction.

        Raises:
            ValueError: If ``position`` is not an ``int`` in ``[1, 2**63)``.
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
            ConversationStoreError: If the store cannot be written.
        """
        _check_position("position", position)
        async with self._lock:
            return await _run_to_completion(self._delete_message_sync, conversation_id, position)

    def _delete_message_sync(self, conversation_id: str, position: int) -> bool:
        with self._transaction("delete a message") as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                raise self._unknown(conversation_id)
            # The marker keeps the position and the device's message id (§4:3,
            # §5:12); the text and every other property are cleared in place.
            deleted = conn.execute(
                "UPDATE messages SET deleted = 1, author = NULL, written_at = NULL, "
                "text = NULL, replies_to = NULL, options = NULL, cut_off = 0 "
                "WHERE conversation_id = ? AND position = ? AND deleted = 0",
                (conversation_id, position),
            ).rowcount
            if not deleted:
                return False
            conn.execute(
                "DELETE FROM chat_changes WHERE kind = 'message_added' "
                "AND conversation_id = ? AND position = ?",
                (conversation_id, position),
            )
            self._record_change(conn, "message_deleted", conversation_id, position=position)
            return True

    async def transcript(
        self,
        conversation_id: str,
        *,
        before: int | None = None,
        limit: int = _DEFAULT_TRANSCRIPT_PAGE,
    ) -> TranscriptPage | None:
        """Read the last ``limit`` entries before ``before``, in one deferred transaction.

        Raises:
            ValueError: If ``before`` or ``limit`` is out of range.
            ConversationStoreError: If the store cannot be read, or a row is corrupt.
        """
        if before is not None:
            _check_position("before", before)
        _check_page_bound("limit", limit)
        async with self._lock:
            read = await _run_to_completion(self._transcript_sync, conversation_id, before, limit)
        if read is None:
            return None
        rows, as_of = read
        try:
            return TranscriptPage(
                conversation_id=conversation_id,
                entries=tuple(_message_from(row) for row in reversed(rows)),
                as_of=as_of,
            )
        except ValidationError as exc:
            msg = f"a stored transcript page is inconsistent: {exc}"
            raise ConversationStoreError(msg) from exc

    def _transcript_sync(
        self, conversation_id: str, before: int | None, limit: int
    ) -> tuple[list[Any], int] | None:
        with self._transaction("read a transcript", immediate=False) as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                return None
            columns = (
                "SELECT conversation_id, position, author, written_at, text, replies_to, "
                "options, cut_off, device_id, message_id, deleted FROM messages "
            )
            if before is None:
                rows = self._fetch(
                    conn,
                    "read a transcript",
                    columns + "WHERE conversation_id = ? ORDER BY position DESC LIMIT ?",
                    (conversation_id, limit),
                )
            else:
                rows = self._fetch(
                    conn,
                    "read a transcript",
                    columns
                    + "WHERE conversation_id = ? AND position < ? ORDER BY position DESC LIMIT ?",
                    (conversation_id, before, limit),
                )
            return rows, self._head(conn)

    async def changes(
        self,
        *,
        after: int,
        conversation_ids: Sequence[str] | None = None,
        limit: int = _DEFAULT_CHANGES_PAGE,
    ) -> ChatChanges:
        """Read every change after ``after``, in one deferred transaction (§5:10, §5:11).

        Raises:
            ValueError: If ``after`` or ``limit`` is out of range, or
                ``conversation_ids`` is malformed.
            ConversationStoreError: If the store cannot be read, or a row is corrupt.
        """
        _check_page_bound("after", after)
        _check_page_bound("limit", limit)
        named = _checked_conversation_ids(conversation_ids)
        if limit == 0:
            return ChatChanges(next_after=after)
        async with self._lock:
            rows, head = await _run_to_completion(self._changes_sync, after, named, limit)
        page = tuple(_change_from(row) for row in rows)
        try:
            return ChatChanges(
                changes=page, next_after=page[-1].seq if len(page) == limit else head
            )
        except ValidationError as exc:
            msg = f"the stored change stream is inconsistent: {exc}"
            raise ConversationStoreError(msg) from exc

    def _changes_sync(
        self, after: int, named: tuple[str, ...] | None, limit: int
    ) -> tuple[list[Any], int]:
        restriction = None if named is None else json.dumps(list(named))
        # One statement for both forms: a ``NULL`` restriction reads every change.
        with self._transaction("read the change stream", immediate=False) as conn:
            rows = self._fetch(
                conn,
                "read the change stream",
                "SELECT c.seq, c.kind, c.conversation_id, c.position, c.devices, "
                "m.conversation_id, m.position, m.author, m.written_at, m.text, m.replies_to, "
                "m.options, m.cut_off, m.device_id, m.message_id, m.deleted "
                "FROM chat_changes c LEFT JOIN messages m ON c.kind = 'message_added' "
                "AND m.conversation_id = c.conversation_id AND m.position = c.position "
                "WHERE c.seq > ? AND (? IS NULL OR c.conversation_id IS NULL OR "
                "c.conversation_id IN (SELECT value FROM json_each(?))) "
                "ORDER BY c.seq ASC LIMIT ?",
                (after, restriction, restriction or "[]", limit),
            )
            return rows, self._head(conn)

    async def my_devices(self) -> tuple[ChatDevice, ...]:
        """Return "my devices", ``device_id`` ascending (ADR-0293 §3:1).

        Raises:
            ConversationStoreError: If the store cannot be read, or a row is corrupt.
        """
        async with self._lock:
            return await _run_to_completion(self._my_devices_sync)

    def _my_devices_sync(self) -> tuple[ChatDevice, ...]:
        with self._transaction("read my devices", immediate=False) as conn:
            return self._devices_of(conn, None)

    async def set_my_devices(self, devices: Sequence[ChatDevice]) -> bool:
        """Replace "my devices" in one ``IMMEDIATE`` transaction (ADR-0293 §3:1).

        Raises:
            ValueError: If ``devices`` is malformed.
            ConversationStoreError: If the store cannot be written.
        """
        wanted = checked_chat_devices(devices)
        async with self._lock:
            return await _run_to_completion(self._set_my_devices_sync, wanted)

    def _set_my_devices_sync(self, wanted: tuple[ChatDevice, ...]) -> bool:
        with self._transaction("set my devices") as conn:
            if self._devices_of(conn, None) == wanted:
                return False
            conn.execute("DELETE FROM chat_devices")
            conn.executemany(
                "INSERT INTO chat_devices(device_id, access) VALUES (?, ?)",
                [(one.device_id, one.access.value) for one in wanted],
            )
            self._record_change(conn, "devices_changed", None, devices=wanted)
            return True

    async def conversation_devices(self, conversation_id: str) -> tuple[ChatDevice, ...] | None:
        """Return a conversation's devices, or ``None`` if absent or stamped (§3:3).

        Raises:
            ConversationStoreError: If the store cannot be read, or a row is corrupt.
        """
        async with self._lock:
            return await _run_to_completion(self._conversation_devices_sync, conversation_id)

    def _conversation_devices_sync(self, conversation_id: str) -> tuple[ChatDevice, ...] | None:
        with self._transaction("read a conversation's devices", immediate=False) as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                return None
            return self._devices_of(conn, conversation_id)

    async def set_conversation_devices(
        self, conversation_id: str, devices: Sequence[ChatDevice]
    ) -> bool:
        """Replace a conversation's devices in one ``IMMEDIATE`` transaction (§3:3).

        Raises:
            ValueError: If ``devices`` is malformed.
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
            ConversationStoreError: If the store cannot be written.
        """
        wanted = checked_chat_devices(devices)
        async with self._lock:
            return await _run_to_completion(
                self._set_conversation_devices_sync, conversation_id, wanted
            )

    def _set_conversation_devices_sync(
        self, conversation_id: str, wanted: tuple[ChatDevice, ...]
    ) -> bool:
        with self._transaction("set a conversation's devices") as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                raise self._unknown(conversation_id)
            if self._devices_of(conn, conversation_id) == wanted:
                return False
            conn.execute(
                "DELETE FROM conversation_devices WHERE conversation_id = ?", (conversation_id,)
            )
            conn.executemany(
                "INSERT INTO conversation_devices(conversation_id, device_id, access) "
                "VALUES (?, ?, ?)",
                [(conversation_id, one.device_id, one.access.value) for one in wanted],
            )
            self._record_change(conn, "devices_changed", conversation_id, devices=wanted)
            return True

    async def take_in(
        self, conversation_id: str, *, positions: Sequence[int], activation_id: str
    ) -> tuple[int, ...]:
        """Mark the named user's messages taken in, in one ``IMMEDIATE`` transaction.

        Raises:
            ValueError: If ``positions`` or ``activation_id`` is malformed.
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
            ConversationStoreError: If the store cannot be written.
        """
        named = _checked_positions(positions)
        activation = _checked_activation_id(activation_id)
        async with self._lock:
            return await _run_to_completion(self._take_in_sync, conversation_id, named, activation)

    def _take_in_sync(
        self, conversation_id: str, named: tuple[int, ...], activation: str
    ) -> tuple[int, ...]:
        with self._transaction("record messages taken in") as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                raise self._unknown(conversation_id)
            if not named:
                return ()
            candidates = self._fetch(
                conn,
                "read the messages to take in",
                "SELECT m.position FROM messages m WHERE m.conversation_id = ? "
                "AND m.deleted = 0 AND m.author = ? "
                "AND m.position IN (SELECT value FROM json_each(?)) "
                "AND NOT EXISTS (SELECT 1 FROM taken_in t WHERE t.conversation_id = "
                "m.conversation_id AND t.position = m.position) ORDER BY m.position ASC",
                (conversation_id, MessageAuthor.USER.value, json.dumps(sorted(set(named)))),
            )
            marked = tuple(_check_stored_position(one[0]) for one in candidates)
            conn.executemany(
                "INSERT INTO taken_in(conversation_id, position, activation_id) VALUES (?, ?, ?)",
                [(conversation_id, one, activation) for one in marked],
            )
            return marked

    async def untaken_messages(
        self, conversation_id: str, *, limit: int = _DEFAULT_AWAITING_PAGE
    ) -> tuple[TranscriptMessage, ...]:
        """Return the user's standing messages not yet taken in (ADR-0293 §6:3, §6:9).

        Raises:
            ValueError: If ``limit`` is outside ``[0, 2**63)``.
            ConversationStoreError: If the store cannot be read, or a row is corrupt.
        """
        _check_page_bound("limit", limit)
        if limit == 0:
            return ()
        async with self._lock:
            rows = await _run_to_completion(self._untaken_sync, conversation_id, limit)
        found: list[TranscriptMessage] = []
        for row in rows:
            message = _message_from(row)
            if not isinstance(message, TranscriptMessage):  # pragma: no cover — `deleted = 0`
                msg = "an untaken message read back as deleted"
                raise ConversationStoreError(msg)
            found.append(message)
        return tuple(found)

    def _untaken_sync(self, conversation_id: str, limit: int) -> list[Any]:
        with self._transaction("read untaken messages", immediate=False) as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                return []
            return self._fetch(
                conn,
                "read untaken messages",
                "SELECT m.conversation_id, m.position, m.author, m.written_at, m.text, "
                "m.replies_to, m.options, m.cut_off, m.device_id, m.message_id, m.deleted "
                "FROM messages m WHERE m.conversation_id = ? AND m.deleted = 0 "
                "AND m.author = ? AND NOT EXISTS (SELECT 1 FROM taken_in t WHERE "
                "t.conversation_id = m.conversation_id AND t.position = m.position) "
                "ORDER BY m.position ASC LIMIT ?",
                (conversation_id, MessageAuthor.USER.value, limit),
            )

    async def conversations_awaiting(
        self, *, limit: int = _DEFAULT_AWAITING_PAGE, after_id: str | None = None
    ) -> list[str]:
        """Page over conversations holding an untaken user's message (ADR-0293 §6:9).

        Raises:
            ValueError: If ``limit`` is outside ``[0, 2**63)``.
            ConversationStoreError: If the store cannot be read.
        """
        _check_page_bound("limit", limit)
        if limit == 0:
            return []
        async with self._lock:
            rows = await _run_to_completion(self._awaiting_sync, limit, after_id)
        return [_stamped_id_of(row[0]) for row in rows]

    def _awaiting_sync(self, limit: int, after_id: str | None) -> list[Any]:
        return self._fetch(
            self._conn,
            "list conversations awaiting the reader",
            "SELECT c.id FROM conversations c WHERE c.deleted_at IS NULL AND c.id > ? "
            "AND EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id "
            "AND m.deleted = 0 AND m.author = ? AND NOT EXISTS (SELECT 1 FROM taken_in t "
            "WHERE t.conversation_id = m.conversation_id AND t.position = m.position)) "
            "ORDER BY c.id ASC LIMIT ?",
            ("" if after_id is None else after_id, MessageAuthor.USER.value, limit),
        )

    async def taken_in(
        self, conversation_id: str, *, positions: Sequence[int]
    ) -> Mapping[int, str]:
        """Return which activation took in each named message, where one did (§6:6).

        Raises:
            ValueError: If ``positions`` is malformed.
            ConversationStoreError: If the store cannot be read, or a row is corrupt.
        """
        named = _checked_positions(positions)
        if not named:
            return {}
        async with self._lock:
            rows = await _run_to_completion(self._taken_in_sync, conversation_id, named)
        found: dict[int, str] = {}
        for row in rows:
            found[_check_stored_position(row[0])] = _checked_stored_activation(row[1])
        return found

    def _taken_in_sync(self, conversation_id: str, named: tuple[int, ...]) -> list[Any]:
        with self._transaction("read messages taken in", immediate=False) as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                return []
            return self._fetch(
                conn,
                "read messages taken in",
                "SELECT position, activation_id FROM taken_in WHERE conversation_id = ? "
                "AND position IN (SELECT value FROM json_each(?))",
                (conversation_id, json.dumps(sorted(set(named)))),
            )
