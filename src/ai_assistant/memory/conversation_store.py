"""A persistent :class:`~ai_assistant.core.protocols.ConversationStore` on SQLite.

Local-first storage (ADR-0002) for ADR-0074's conversation index: the durable
identity of a conversation, and the ordered turns recorded under it. It holds no
content — a turn's content is one ``EpisodicMemory`` in the ``MemoryStore``, named
here by a derived episode id — so this store needs no embedder and no vector
table, which is the whole of why it is a second store rather than a widening of
the first (ADR-0074 §9).

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

**A turn cannot name a conversation that does not exist** (#452). ``turns``
carries a foreign key to ``conversations`` with ``ON DELETE CASCADE``, and
enforcement is switched on for the connection at open — ``PRAGMA foreign_keys``
is off by default and is *per connection*, so it has to be. Two consequences the
statements below are written against:

* The only ``INSERT`` into ``turns`` already proves the parent exists inside the
  same ``IMMEDIATE`` transaction, so the constraint never fires on this
  module's own writes; it is there for a writer that is not this module. Were it
  ever to fire, the ``IntegrityError`` reaches the caller as this seam's error
  like any other backend failure.
* :meth:`SqliteConversationStore.drop_if_eligible` keeps deleting the index
  rows *explicitly* before the record, rather than leaning on the cascade —
  see the comment there for why the pragma's per-connection scope makes that the
  safer of the two.

The constraint binds a database written before it existed only after a rebuild,
which :meth:`SqliteConversationStore._migrate_turns` performs at open. An orphan
that predates all of this is *reported* rather than repaired: the two reverse
lookups and the export left-join the conversation so a turn naming nothing
surfaces as ``ConversationStoreError`` instead of vanishing from every read.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import ConversationStoreError, UnknownConversationError
from ai_assistant.core.types import (
    FIRST_TURN_ORDINAL,
    Conversation,
    ConversationExport,
    ConversationTurn,
    ParkedBinding,
    SpokenDelivery,
    SpokenDeliveryState,
    describe_untrusted,
)
from ai_assistant.memory._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

    from ai_assistant.core.clock import Clock

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

#: The configured replay window :meth:`SqliteConversationStore.turns` uses when a
#: caller names no ``limit`` (ADR-0074 §9.3): finite, and the same for everyone.
_DEFAULT_TAIL_LIMIT = 20

#: The default batch :meth:`SqliteConversationStore.episodes_to_purge` yields.
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

#: The reserved namespace a captured turn's episode id is minted into (ADR-0074
#: §3): structurally recognisable, and no other producer may mint into it.
_EPISODE_NAMESPACE = "conv"

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

#: ADR-0205 §3's fact, spelled as three nullable columns rather than one blob: the
#: state as its ``StrEnum`` value, and each duration as a whole number of
#: microseconds, which is ``timedelta``'s own resolution and so exact in both
#: directions. A row whose ``delivery_state`` is ``NULL`` carries **no delivery fact**
#: — on the surface as it stands, a turn that did not run on ``converse_spoken`` — and
#: is left exactly as it stands by :meth:`SqliteConversationStore.record_delivery`.
#:
#: Three columns rather than a JSON member for ``parked``'s reason one field over: the
#: partition ADR-0205 §2 fixes is enforced by the ``core`` model on the way out, and a
#: column per member is what lets a stored row's corruption surface as this seam's own
#: error rather than as a decode of text nobody validated.
#:
#: ``TEXT`` for the state and ``INTEGER`` microseconds for the two durations, each
#: nullable because ``UNKNOWN`` carries neither and an absent delivery carries none of
#: the three.
_DELIVERY_COLUMNS: Final = "delivery_state TEXT, delivery_played INTEGER, delivery_rendered INTEGER"

#: What a SQLite ``INTEGER`` holds: a signed 64-bit value. A duration beyond it is
#: refused by :func:`_to_micros_of` as this seam's own error rather than left to raise
#: the driver's ``OverflowError``, which is not a ``sqlite3.Error`` and so would cross
#: :meth:`SqliteConversationStore._transaction`'s translation untouched.
_SQLITE_INT_BOUND: Final = 2**63

#: The columns of the ``turns`` table, foreign key and all — held in one place so
#: the fresh-database path and :meth:`SqliteConversationStore._migrate_turns`'
#: rebuild cannot drift apart. Two spellings of one schema is how a migration
#: ends up producing a table subtly unlike the one a fresh open produces.
_TURNS_COLUMNS = (
    "conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, "
    "ordinal INTEGER NOT NULL, episode_id TEXT NOT NULL, occurred_at INTEGER NOT NULL, "
    "execution_id TEXT, step_id TEXT, " + _DELIVERY_COLUMNS + ", "
    "PRIMARY KEY(conversation_id, ordinal)"
)

#: The turn columns every read selects, aliased to ``t`` for the joins. The unaliased
#: spelling is written out at each of the three reads that needs it rather than held
#: here: ruff's ``S608`` reads a query assembled from a name as a possible injection
#: vector whatever the name holds, and a literal at the call site is the cheaper answer
#: than a suppression on each of them. What keeps the four in step is
#: :meth:`SqliteConversationStore._decode_turn`, which every one of them feeds and which
#: fails loudly on a row whose positions have moved.
_TURN_SELECT = (
    "t.conversation_id, t.ordinal, t.episode_id, t.occurred_at, t.execution_id, t.step_id, "
    "t.delivery_state, t.delivery_played, t.delivery_rendered"
)

#: ADR-0212 §1's watermark, one nullable column with no default on the *conversation*
#: — the row whose progress it records, and the store that allocated the ordinal it
#: names. Held apart from the fresh-database ``CREATE TABLE`` for
#: :meth:`SqliteConversationStore._migrate_observed` to add to a file written before
#: it, exactly as :data:`_DELIVERY_COLUMNS` is one table down.
#:
#: **Nullable and defaultless is a contract obligation, not a convenience**
#: (ADR-0212 §7): SQLite adds such a column in constant time without rewriting a row,
#: every existing conversation comes back carrying no watermark, and a build written
#: before this member — which names only the columns it knows in its
#: ``INSERT INTO conversations(...)`` — goes on inserting against the upgraded file. A
#: ``NOT NULL`` column with no default would make that build's ``start`` fail, which
#: is a refusal to serve over a watermark arriving through the schema.
_OBSERVED_COLUMN: Final = "observed_through INTEGER"

#: **The seven columns every conversation read selects**, written out at each of the
#: five reads that needs them rather than held in a name here — :data:`_TURN_SELECT`'s
#: reason one table down, that ruff's ``S608`` reads a query assembled from a name as a
#: possible injection vector whatever the name holds, and a literal at the call site is
#: the cheaper answer than a suppression on each of them. The seven are the five stored
#: columns, ``observed_through``, and the conversation's **highest turn ordinal**
#: derived beside them as
#: ``(SELECT MAX(t.ordinal) FROM turns t WHERE t.conversation_id = c.id)``.
#:
#: The derived column is not decoration. ADR-0212 §7 discards a watermark "above the
#: highest ordinal the conversation holds", and that judgement is **the store's**, made
#: where the record is built — so every read that builds a :class:`Conversation` has to
#: have the figure in hand or it cannot make it. What keeps the five in step is
#: :meth:`SqliteConversationStore._decode_conversation`, which every one of them feeds.


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
            # Absorb the cancellation and keep waiting on the worker's physical
            # completion signal, so the lock outlives the still-running thread.
            cancellation = exc
            pending = loop.run_in_executor(None, done.wait)
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

    This is the one read whose caller *destroys* what it is handed, so coercing a
    corrupt value — ``str()`` on a ``BLOB`` yields a plausible-looking
    ``"b'...'"`` — would send a sweep to delete an id nothing holds, and then let
    it drop the index row that named the real episode. Every other read reaches a
    frozen type whose ``Identifier`` refuses the same values; this one does not,
    so it makes the check itself.

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

    ``NULL`` in ``delivery_state`` is **absence** and not a state: it is what every
    turn that did not run on ``converse_spoken`` carries, and what every turn written
    before ADR-0205 landed carries after :meth:`SqliteConversationStore._migrate_delivery`.
    The two durations are read only where a state is present, so a stray microsecond
    beside a ``NULL`` state cannot conjure a delivery out of half a row.

    The partition itself is not re-checked here. :class:`SpokenDelivery`'s validator
    owns it and a row that breaches it raises ``ValidationError``, which
    :meth:`SqliteConversationStore._decode_turn` already translates into this seam's
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
        msg = f"a stored turn carries an unknown delivery state: {describe_untrusted(state)}"
        raise ConversationStoreError(msg) from exc
    return SpokenDelivery(
        state=member,
        played=None if played is None else timedelta(microseconds=_micros_of(played)),
        rendered=None if rendered is None else timedelta(microseconds=_micros_of(rendered)),
    )


def _refuse_unknown_delivery(delivery: SpokenDelivery) -> None:
    """Refuse an ``UNKNOWN`` report before any I/O (ADR-0205 §3).

    ``UNKNOWN`` is written by capture and only through ``append``; it is not a value
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
            "by capture through append, and a device that does not know reports nothing "
            "(ADR-0205 §2, §3)"
        )
        raise ValueError(msg)


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
            f"store can hold, so the turn's delivery was not written (ADR-0205 §3)"
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
        msg = f"a stored turn carries a delivery duration that is not an integer: {value!r}"
        raise ConversationStoreError(msg)
    return value


def _ordinal_of(value: object) -> int:
    """Read a stored ordinal, refusing anything outside the domain one can have.

    The same affinity argument :func:`_instant_from` makes, plus the range: a
    ``REAL`` in an ``INTEGER`` column is a store fault, and coercing one would
    hand back a turn at a position no append ever allocated. The *whole* domain is
    checked here rather than in pieces, because every caller needs the same
    answer — the reader that decodes a row, the cursor that places a sweep, and
    the allocator that adds one to the highest.

    Raises:
        ConversationStoreError: If the stored value is not an exact ``int`` in
            ``[FIRST_TURN_ORDINAL, 2**63)``.
    """
    if type(value) is not int or not FIRST_TURN_ORDINAL <= value < _PAGE_BOUND:
        msg = f"a stored ordinal is not a usable position: {describe_untrusted(value)}"
        raise ConversationStoreError(msg)
    return value


def _usable_watermark(stored: object, highest: object) -> int | None:
    """Read a stored observation watermark, discarding one this build cannot use.

    ADR-0212 §7's disposition, and the one place it is decided: a value that is
    **not an integer**, is **below** :data:`FIRST_TURN_ORDINAL`, or is **above the
    highest ordinal the conversation holds** is discarded, and the conversation is
    read as one with no watermark at all. It is never levelled, never advanced past
    a value that could not be read, and — the part that matters most — **never an
    error**. :func:`_ordinal_of`'s posture is deliberately not taken here: a
    watermark is bookkeeping that holds no evidence and answers no query, so letting
    a bad one raise would make a conversation unreadable through ``get``, ``recent``,
    ``turns`` and ``export`` because a column the user never sees is wrong, which is
    exactly the outcome ADR-0111 §7 forbids arriving through a different door.

    ``highest`` is the conversation's highest turn ordinal, or ``None`` where it
    holds no turn — in which case **no** watermark is supported and every value is
    discarded. A ``highest`` that is not itself a usable integer is treated the same
    way rather than raised on, which is the conservative direction: a corrupt
    *ordinal* surfaces as this seam's error where a turn is decoded, and there is
    nothing to be gained by having a conversation refuse to be read as well.

    Args:
        stored: The raw ``observed_through`` column value.
        highest: The raw ``MAX(ordinal)`` of the conversation's turns.

    Returns:
        The watermark, or ``None`` where there is none this build can use.
    """
    if type(stored) is not int or not FIRST_TURN_ORDINAL <= stored < _PAGE_BOUND:
        return None
    if type(highest) is not int or not FIRST_TURN_ORDINAL <= highest < _PAGE_BOUND:
        return None
    return stored if stored <= highest else None


def _check_page_bound(name: str, value: object, *, floor: int = 0) -> None:
    """Refuse a paging argument that is not an exact ``int`` in ``[floor, 2**63)``.

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
        ValueError: If ``value`` is not an ``int``, is below ``floor``, or is
            beyond the signed 64-bit range.
    """
    if type(value) is not int or not floor <= value < _PAGE_BOUND:
        msg = f"{name} must be an int in [{floor}, 2**63), got {describe_untrusted(value)}"
        raise ValueError(msg)


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
        tail_limit: int = _DEFAULT_TAIL_LIMIT,
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
            tombstone_grace: How long a stamped conversation's index outlives the
                stamp (ADR-0074 §8).
            tail_limit: The configured replay window :meth:`turns` uses by default.
            purge_batch: The batch size :meth:`episodes_to_purge` uses by default.

        Raises:
            ValueError: If ``tombstone_grace`` is not strictly positive, if
                ``retention`` is set and not strictly positive, or if either
                default page size is out of range. The two durations are refused
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
        _check_page_bound("tail_limit", tail_limit)
        _check_page_bound("purge_batch", purge_batch)
        self._clock = checked_clock(now, owner="SqliteConversationStore")
        self._new_id = new_id
        self._retention = retention
        self._grace = tombstone_grace
        self._tail_limit = tail_limit
        self._purge_batch = purge_batch
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    # --- opening -------------------------------------------------------------

    def _setup(self) -> sqlite3.Connection:
        """Open the connection and create the schema, or fail with the seam's error."""
        try:
            # `isolation_level=None` puts the driver in autocommit mode, so every
            # transaction below is an explicit `BEGIN ... COMMIT` this module
            # controls. The implicit transactions the driver would otherwise open
            # are *deferred*, upgrading to a write lock only at the first write —
            # which leaves a read-then-write mutation open to exactly the
            # interleaving the exclusion exists to forbid.
            conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        except (sqlite3.Error, OSError) as exc:
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
            self._restrict_permissions()
            conn.execute(
                "CREATE TABLE IF NOT EXISTS conversations("
                "id TEXT PRIMARY KEY, started_at INTEGER NOT NULL, "
                "last_active_at INTEGER NOT NULL, last_turn_at INTEGER, deleted_at INTEGER, "
                + _OBSERVED_COLUMN
                + ")"
            )
            # Straight after the table it belongs to, and for the same reason
            # `_migrate_delivery` runs one table down: `CREATE TABLE IF NOT EXISTS`
            # is a no-op against a file that already holds `conversations`, so a
            # database written before ADR-0212 would otherwise fail its first read
            # on a column that is not there.
            self._migrate_observed(conn)
            conn.execute("CREATE TABLE IF NOT EXISTS turns(" + _TURNS_COLUMNS + ")")
            # Before the indexes, because the rebuild drops the table and takes
            # them with it. It switches enforcement off for itself, because a
            # legacy file may already hold a row the constraint would refuse.
            self._migrate_turns(conn)
            # After the rebuild rather than before it: a rebuild writes the current
            # schema and so already carries these, and running this first would add
            # columns to a table about to be dropped.
            self._migrate_delivery(conn)
            # The two uniqueness invariants the store *proves* rather than asks a
            # caller to keep (ADR-0074 §9.1): one turn per episode id, and one turn
            # per parked binding. In the schema, so a second writer racing the
            # in-transaction check cannot land the row that check refused.
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS turns_episode ON turns(episode_id)")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS turns_binding "
                "ON turns(execution_id, step_id) WHERE execution_id IS NOT NULL"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS conversations_activity "
                "ON conversations(last_active_at DESC, id)"
            )
            self._set_foreign_keys(conn, enforced=True)
        except ConversationStoreError:
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
        what makes the constraint in :data:`_TURNS_COLUMNS` mean anything at all — a
        schema carrying a key nobody enforces is documentation.

        **Both** directions are set rather than assumed. Enforcement being off is
        the documented default, but it is a *compile-time* default: a driver built
        with ``SQLITE_DEFAULT_FOREIGN_KEYS`` starts with it on, and
        :meth:`_migrate_turns` copying a legacy orphan under enforcement would fail
        and make that file unopenable — the exact outcome the migration is written
        to avoid. Saying so explicitly makes the rebuild's semantics independent of
        how the driver happens to have been compiled.

        Reading the setting back is the point of the method rather than a flourish:
        the statement is a **silent no-op** in a build compiled with
        ``SQLITE_OMIT_FOREIGN_KEY`` and inside an open transaction alike, and either
        way the store would go on believing something about a setting it had not
        changed. Both calls are issued at open, where nothing has begun one.

        A build that omits foreign keys altogether reads back ``0`` whatever is
        asked of it, so it satisfies the ``enforced=False`` call and fails the
        ``enforced=True`` one — loudly, at construction, which is where to discover
        that this store cannot keep its own invariant.

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
                "this SQLite build does not enforce foreign keys, so a turn could not be "
                "kept from naming a conversation that does not exist"
                if enforced
                else "foreign key enforcement could not be switched off for the schema rebuild"
            )
            raise ConversationStoreError(msg)

    @staticmethod
    def _turns_reference_conversations(conn: sqlite3.Connection) -> bool:
        """Whether ``turns`` already carries the cascading key to ``conversations``.

        Read off ``PRAGMA foreign_key_list`` rather than the stored DDL text,
        because the whole *shape* is what decides whether a rebuild is owed: the
        right child column, the right parent column, and ``ON DELETE CASCADE``. A
        substring match on ``sqlite_master`` would accept a key pointing at the
        right table through the wrong column, and skip the migration that would
        have fixed it.
        """
        return any(
            row[2] == "conversations"
            and row[3] == "conversation_id"
            and row[4] == "id"
            and str(row[6]).upper() == "CASCADE"
            for row in conn.execute("PRAGMA foreign_key_list(turns)")
        )

    def _migrate_turns(self, conn: sqlite3.Connection) -> None:
        """Rebuild a pre-existing ``turns`` table that carries no foreign key (#452).

        ``CREATE TABLE IF NOT EXISTS`` is a no-op against a file whose ``turns``
        table already exists, so the constraint above binds **fresh databases
        only**; a store opened over a database written before it would go on
        accepting rows that name nothing. SQLite has no ``ADD CONSTRAINT``, so
        making it bind an existing file is a table rebuild — the shape
        ``SqliteMemoryStore._migrate_records`` already carries in this repo.

        The copy runs with enforcement **switched off, explicitly**, and that is
        deliberate rather than a reliance on the default. A legacy file may already
        hold an orphan, and enforcing during the copy would make that file
        *unopenable* rather than readable: no read could reach the sound rows
        beside the broken one, and the fault would surface as a failure to
        construct the store rather than as the report the contract owes. The orphan
        therefore survives the rebuild and is named by the reads that would
        otherwise join it away. Saying ``OFF`` rather than trusting the ordering
        against :meth:`_set_foreign_keys` matters because "off" is only a
        *compile-time* default — a driver built with ``SQLITE_DEFAULT_FOREIGN_KEYS``
        starts with it on, and this rebuild would refuse the very row it exists to
        carry across.

        No ``rowid`` is carried forward, unlike the memory store's rebuild: nothing
        joins ``turns`` by rowid, and a turn's identity is its
        ``(conversation_id, ordinal)`` pair.

        It runs in an **explicit** transaction, because SQLite auto-commits a bare
        DDL statement in autocommit mode (issue #289's review): without the
        ``BEGIN``, a failure during the row copy would leave the table swapped and
        the rows lost — permanently, since a later open would find the foreign key
        and skip the migration. ``DROP TABLE`` takes the table's indexes with it,
        which is why this runs *before* the ``CREATE ... IF NOT EXISTS`` index
        statements that put them back.
        """
        if self._turns_reference_conversations(conn):
            return  # already on the constrained schema; nothing to do
        # Outside the `BEGIN` below, where the pragma would be a silent no-op.
        self._set_foreign_keys(conn, enforced=False)
        conn.execute("BEGIN")
        try:
            conn.execute("CREATE TABLE turns_migrated(" + _TURNS_COLUMNS + ")")
            # Streamed through a dedicated read cursor rather than ``fetchall()``,
            # so migrating a long history does not materialise the whole table at
            # once. Reads come from ``turns`` and writes go to ``turns_migrated``,
            # a different table, so the scan cursor stays valid across the inserts.
            read = conn.execute(
                "SELECT conversation_id, ordinal, episode_id, occurred_at, execution_id, step_id "
                "FROM turns"
            )
            for row in read:
                # The six columns a pre-foreign-key file can be relied on to have.
                # A file old enough to want this rebuild predates ADR-0205's three
                # entirely, and :meth:`_migrate_delivery` — which runs after this —
                # finds them already present on the table this writes, so every
                # carried-across turn lands carrying no delivery. Which is what
                # ADR-0205 §3 says of a turn that did not run on ``converse_spoken``,
                # and true of every one of them.
                conn.execute(
                    "INSERT INTO turns_migrated(conversation_id, ordinal, episode_id, "
                    "occurred_at, execution_id, step_id) VALUES (?, ?, ?, ?, ?, ?)",
                    row,
                )
            conn.execute("DROP TABLE turns")
            conn.execute("ALTER TABLE turns_migrated RENAME TO turns")
            conn.execute("COMMIT")
        except BaseException:
            # The whole rewrite, DDL included, has to come undone: a reopen then
            # re-attempts a clean migration instead of finding a half-swapped
            # schema. A crash mid-rebuild is covered too — SQLite discards the
            # uncommitted transaction on the next open.
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            raise

    @staticmethod
    def _migrate_delivery(conn: sqlite3.Connection) -> None:
        """Add ADR-0205 §3's three columns to a ``turns`` table written before them.

        ``CREATE TABLE IF NOT EXISTS`` is a no-op against a file whose ``turns``
        table already exists, so the columns in :data:`_TURNS_COLUMNS` bind **fresh
        databases only** — and a store opened over a database written by a build
        before this one would fail its first read on a column that is not there.

        **An ``ALTER TABLE ... ADD COLUMN`` rather than the rebuild
        :meth:`_migrate_turns` performs**, because that is the whole of what is
        owed: the three are nullable with no default, so SQLite adds each in
        constant time without rewriting a row, and every existing turn comes back
        carrying no delivery — which is exactly what ADR-0205 §3's absence clause
        says of a turn that did not run on ``converse_spoken``, and true of every
        turn written before the operation existed.

        Each column is added on its own and only where it is missing, so a database
        left half-migrated by an interrupted upgrade is finished rather than
        refused. ``PRAGMA table_info`` is read rather than the stored DDL text, for
        :meth:`_turns_reference_conversations`' reason: what decides is the shape
        the table actually has.
        """
        present = {str(row[1]) for row in conn.execute("PRAGMA table_info(turns)")}
        for column in _DELIVERY_COLUMNS.split(", "):
            if column.split(" ")[0] not in present:
                conn.execute("ALTER TABLE turns ADD COLUMN " + column)

    @staticmethod
    def _migrate_observed(conn: sqlite3.Connection) -> None:
        """Add ADR-0212 §7's watermark column to a ``conversations`` table without it.

        :meth:`_migrate_delivery`'s shape one table up, and the ADR names that
        migration as the precedent to apply: the column is nullable with no default,
        so SQLite adds it in constant time **without rewriting a row**, every
        conversation written before it comes back carrying no watermark — which §4
        reads as a walk that has not started — and no existing column changes.

        An ``ALTER TABLE ... ADD COLUMN`` rather than the rebuild
        :meth:`_migrate_turns` performs, because that is the whole of what is owed.
        ``PRAGMA table_info`` is read rather than the stored DDL text, for
        :meth:`_turns_reference_conversations`' reason: what decides is the shape the
        table actually has.
        """
        present = {str(row[1]) for row in conn.execute("PRAGMA table_info(conversations)")}
        if _OBSERVED_COLUMN.split(" ")[0] not in present:
            conn.execute("ALTER TABLE conversations ADD COLUMN " + _OBSERVED_COLUMN)

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
        transaction is rolled back — which is how :meth:`append` refuses a
        duplicate binding without consuming an ordinal or leaving a row behind.

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

        The row is the seven columns :data:`_CONVERSATION_SELECT` names — the five
        stored ones, the raw watermark, and the conversation's highest turn ordinal
        — because ADR-0212 §7 makes discarding an unusable watermark **the store's**
        act, made where the record is built, and the judgement needs the last of the
        seven. The discard itself is :func:`_usable_watermark`'s and is deliberately
        not a fault: a watermark this build cannot use comes back absent rather than
        raising, so one wrong bookkeeping integer cannot make a conversation
        unreadable.

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
                observed_through=_usable_watermark(row[5], row[6]),
            )
        except (ValidationError, TypeError, OverflowError) as exc:
            msg = f"a stored conversation could not be decoded: {exc}"
            raise ConversationStoreError(msg) from exc

    @classmethod
    def _decode_turn(cls, row: Sequence[Any]) -> ConversationTurn:
        """Rebuild a :class:`ConversationTurn` from its row, surfacing corruption.

        Raises:
            ConversationStoreError: If the stored row does not validate.
        """
        # The binding is a *pair*, so a row carrying half of one is corrupt — and
        # the half that would otherwise pass unnoticed is `(NULL, 's')`, which a
        # check on `execution_id` alone reads as an unparked turn and hands back
        # as a plausible-but-wrong record, losing the durable recovery binding.
        # This module always writes both columns in one statement, so the pair can
        # only break through something outside the store; the guard therefore sits
        # where the store reads foreign data, which is where the contract's
        # promise about a corrupt row lives.
        if (row[4] is None) != (row[5] is None):
            msg = (
                f"a stored turn carries half a parked binding: "
                f"execution_id={describe_untrusted(row[4])}, step_id={describe_untrusted(row[5])}"
            )
            raise ConversationStoreError(msg)
        try:
            parked = None if row[4] is None else ParkedBinding(execution_id=row[4], step_id=row[5])
            return ConversationTurn(
                conversation_id=row[0],
                ordinal=_ordinal_of(row[1]),
                episode_id=cls._verified_episode_id(row[0], _ordinal_of(row[1]), row[2]),
                occurred_at=_instant_from(row[3], what="occurred_at"),
                parked=parked,
                delivery=_delivery_from(row[6], row[7], row[8]),
            )
        except (ValidationError, TypeError, OverflowError) as exc:
            msg = f"a stored turn could not be decoded: {exc}"
            raise ConversationStoreError(msg) from exc

    @classmethod
    def _verified_episode_id(cls, conversation_id: str, ordinal: int, stored: object) -> str:
        """Return the stored episode id, having checked it is the one derived.

        The id is a *function* of the conversation and the ordinal (ADR-0074 §3),
        so a stored value that is not that function's output is a store fault, not
        a variant. It matters most on the destructive path: a sweep handed a
        foreign id would delete something that is not this turn's episode — or
        nothing at all — and then drop the index row that named the real one,
        leaving it orphaned with nothing left pointing at it.

        Raises:
            ConversationStoreError: If the stored id is not the derived one.
        """
        expected = cls._episode_id(conversation_id, ordinal)
        if _episode_id_of(stored) != expected:
            described = describe_untrusted(stored)
            msg = f"a stored episode id is not the one this turn derives: {described}"
            raise ConversationStoreError(msg)
        return expected

    @staticmethod
    def _episode_id(conversation_id: str, ordinal: int) -> str:
        """Derive a turn's episode id from the two values the store proved unique.

        Reserved to captured conversation turns (ADR-0074 §3): no other producer
        mints into this namespace, so a collision inside it is a broken invariant
        rather than bad luck.
        """
        return f"{_EPISODE_NAMESPACE}:{conversation_id}:{ordinal}"

    @classmethod
    def _row_of(cls, conn: sqlite3.Connection, conversation_id: str) -> Sequence[Any] | None:
        """Read one conversation row inside an open transaction, or ``None``."""
        rows = cls._fetch(
            conn,
            "read a conversation",
            "SELECT c.id, c.started_at, c.last_active_at, c.last_turn_at, c.deleted_at, "
            "c.observed_through, (SELECT MAX(t.ordinal) FROM turns t "
            "WHERE t.conversation_id = c.id) "
            "FROM conversations c WHERE c.id = ?",
            (conversation_id,),
        )
        return rows[0] if rows else None

    @staticmethod
    def _orphan(conversation_id: object) -> ConversationStoreError:
        """The fault a turn naming no conversation is (#452).

        The base class and not :meth:`_unknown`'s subclass: the caller named
        something the store *does* hold a turn for, so this is not "another sweeper
        already finished this id" (ADR-0076 §2) — it is the index disagreeing with
        itself, which is a store fault.
        """
        described = describe_untrusted(conversation_id)
        return ConversationStoreError(
            f"a stored turn names a conversation that is absent: {described}"
        )

    def _presented_turn(self, rows: Sequence[Any]) -> ConversationTurn | None:
        """Decode a reverse lookup's row: report an orphan, withhold a tombstone.

        The two lookups **left**-join the conversation rather than requiring it,
        because an inner join answers "no such turn" for two rows that are nothing
        alike: one whose conversation is stamped, withheld on purpose (ADR-0074
        §9), and one whose conversation does not exist at all, which is corruption
        the contract owes an error for. Joining the second away is the worst of the
        options — the row is invisible to every read *and* unreachable by the purge
        walk, which needs the conversation record to enumerate anything, so the
        episode it names could never be destroyed (#452).

        ``c.id IS NULL`` is an unambiguous "no parent row" here even though SQLite
        tolerates a ``NULL`` in a ``TEXT PRIMARY KEY``: the join predicate is
        ``c.id = t.conversation_id``, and a ``NULL`` id matches nothing.

        Raises:
            ConversationStoreError: If the turn names a conversation the store does
                not hold, or the row itself does not decode.
        """
        if not rows:
            return None
        row = rows[0]
        # The two joined conversation columns sit **after** every turn column, so
        # their positions move with :data:`_TURN_SELECT` rather than being written
        # out twice; a literal 6 and 7 here is what a column added to the turn would
        # silently break.
        joined = _TURN_SELECT.count(",") + 1
        if row[joined] is None:
            raise self._orphan(row[0])
        if row[joined + 1] is not None:
            return None
        return self._decode_turn(row)

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
                "INSERT INTO conversations(id, started_at, last_active_at, last_turn_at, "
                "deleted_at) VALUES (?, ?, ?, NULL, NULL)",
                (
                    conversation.id,
                    _to_micros(conversation.started_at),
                    _to_micros(conversation.last_active_at),
                ),
            )
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
            "SELECT c.id, c.started_at, c.last_active_at, c.last_turn_at, c.deleted_at, "
            "c.observed_through, (SELECT MAX(t.ordinal) FROM turns t "
            "WHERE t.conversation_id = c.id) "
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

    async def append(
        self,
        conversation_id: str,
        *,
        occurred_at: datetime,
        parked: ParkedBinding | None = None,
        delivery: SpokenDelivery | None = None,
    ) -> ConversationTurn:
        """Allocate the ordinal, derive the episode id, and record the turn.

        Allocation, derivation and the write are one transaction, so two engines
        cannot derive one id for two turns (ADR-0074 §3). A duplicate binding is
        refused before anything is allocated and the transaction is rolled back,
        so no ordinal is consumed and no row is left behind (§9.1).

        Raises:
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
            ConversationStoreError: If ``parked`` duplicates a binding already
                claimed, or the store cannot be written.
            ValueError: If ``occurred_at`` is not a timezone-aware instant.
        """
        async with self._lock:
            row = await _run_to_completion(
                self._append_sync, conversation_id, occurred_at, parked, delivery
            )
        return self._decode_turn(row)

    def _append_sync(
        self,
        conversation_id: str,
        occurred_at: datetime,
        parked: ParkedBinding | None,
        delivery: SpokenDelivery | None,
    ) -> Sequence[Any]:
        with self._transaction("append a turn") as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                raise self._unknown(conversation_id)
            if parked is not None:
                claimed = self._fetch(
                    conn,
                    "check a parked binding",
                    "SELECT 1 FROM turns WHERE execution_id = ? AND step_id = ?",
                    (parked.execution_id, parked.step_id),
                )
                if claimed:
                    msg = (
                        f"a turn already parked on execution {parked.execution_id!r} "
                        f"step {parked.step_id!r}"
                    )
                    raise ConversationStoreError(msg)
            highest, stored = self._fetch(
                conn,
                "allocate an ordinal",
                "SELECT MAX(ordinal), COUNT(*) FROM turns WHERE conversation_id = ?",
                (conversation_id,),
            )[0]
            if highest is None:
                ordinal = FIRST_TURN_ORDINAL
            else:
                # Density is exactly `MAX == COUNT` when the numbering starts at
                # one, which is the cheap total check. A gap can only come from
                # outside this module — rows go when the record is dropped and
                # never one at a time — and allocating past one would *extend* the
                # corruption rather than report it, leaving an index whose walks
                # no longer agree with the ordinals they visit.
                last = _ordinal_of(highest)
                if last != stored:
                    msg = (
                        f"conversation {describe_untrusted(conversation_id)} has a gapped "
                        f"turn index: {stored} turns ending at ordinal {last}"
                    )
                    raise ConversationStoreError(msg)
                ordinal = last + 1
            if ordinal >= _PAGE_BOUND:
                # Unreachable by appending — ordinals start at 1 and move by one —
                # so this is a corrupt or hostile row. It still owes this seam's
                # error rather than the `OverflowError` binding the value would
                # raise, which is what the contract promises for a store fault.
                msg = f"conversation {describe_untrusted(conversation_id)} has no ordinal left"
                raise ConversationStoreError(msg)
            # Built before anything is written, because `occurred_at` is the one
            # argument this seam cannot vouch for: a naive value is refused rather
            # than silently localised to the host's zone (ADR-0023 §3), and the
            # rollback leaves the ordinal unconsumed.
            turn = ConversationTurn(
                conversation_id=conversation_id,
                ordinal=ordinal,
                episode_id=self._episode_id(conversation_id, ordinal),
                occurred_at=occurred_at,
                parked=parked,
                delivery=delivery,
            )
            stamp = _to_micros(turn.occurred_at)
            row = (
                turn.conversation_id,
                turn.ordinal,
                turn.episode_id,
                stamp,
                None if parked is None else parked.execution_id,
                None if parked is None else parked.step_id,
                *_delivery_row(delivery),
            )
            conn.execute(
                "INSERT INTO turns(conversation_id, ordinal, episode_id, occurred_at, "
                "execution_id, step_id, delivery_state, delivery_played, delivery_rendered) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
            conn.execute(
                "UPDATE conversations SET last_turn_at = ? WHERE id = ?",
                (stamp, conversation_id),
            )
            return row

    async def record_delivery(
        self, conversation_id: str, *, episode_id: str, delivery: SpokenDelivery
    ) -> ConversationTurn | None:
        """Stamp the named turn's delivery, if and only if it is still ``UNKNOWN``.

        The read of the three conditions and the write are one ``IMMEDIATE``
        transaction, so two reports observing ``UNKNOWN`` cannot both write: the
        second finds a state that is no longer ``UNKNOWN`` and performs nothing,
        which is ADR-0205 §1's stamped-once rule held across processes and not only
        across coroutines on one loop.

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
            row = await _run_to_completion(
                self._record_delivery_sync, conversation_id, episode_id, delivery
            )
        return None if row is None else self._decode_turn(row)

    def _record_delivery_sync(
        self, conversation_id: str, episode_id: str, delivery: SpokenDelivery
    ) -> Sequence[Any] | None:
        with self._transaction("record a turn's delivery") as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                raise self._unknown(conversation_id)
            # All three of ADR-0205 §3's conditions in one predicate, so the row is
            # written only where every one of them held at the moment of writing —
            # the conversation, the episode, and a recorded state of ``UNKNOWN``. A
            # row carrying no delivery at all fails the third and is left as it
            # stands: this operation is not a way to give such a turn one.
            written = conn.execute(
                "UPDATE turns SET delivery_state = ?, delivery_played = ?, "
                "delivery_rendered = ? WHERE conversation_id = ? AND episode_id = ? "
                "AND delivery_state = ?",
                (
                    *_delivery_row(delivery),
                    conversation_id,
                    episode_id,
                    SpokenDeliveryState.UNKNOWN.value,
                ),
            ).rowcount
            if not written:
                return None
            stamped = self._fetch(
                conn,
                "read the stamped turn",
                "SELECT conversation_id, ordinal, episode_id, occurred_at, execution_id, "
                "step_id, delivery_state, delivery_played, delivery_rendered "
                "FROM turns WHERE conversation_id = ? AND episode_id = ?",
                (conversation_id, episode_id),
            )
            if not stamped:  # pragma: no cover — the row was just updated in this transaction
                return None
            written_row: Sequence[Any] = stamped[0]
            return written_row

    async def record_observed(
        self, conversation_id: str, *, through_ordinal: int
    ) -> Conversation | None:
        """Advance the watermark if it moves it forward without leading the turns.

        The read of the two conditions and the write are one ``IMMEDIATE``
        transaction, so two concurrent advances cannot both write from the same
        reading: the second observes the position the first left and performs
        nothing, which is ADR-0212 §5's monotonicity held **across processes** and
        not only across coroutines on one loop. That is the whole of what makes two
        overlapping observation passes safe.

        The range refusal is **before the lock and before any I/O**, on ADR-0085
        §3's convention.

        Raises:
            ValueError: If ``through_ordinal`` is outside
                ``[FIRST_TURN_ORDINAL, 2**63)``.
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
            ConversationStoreError: If the store cannot be written.
        """
        _check_page_bound("through_ordinal", through_ordinal, floor=FIRST_TURN_ORDINAL)
        async with self._lock:
            row = await _run_to_completion(
                self._record_observed_sync, conversation_id, through_ordinal
            )
        return None if row is None else self._decode_conversation(row)

    def _record_observed_sync(
        self, conversation_id: str, through_ordinal: int
    ) -> Sequence[Any] | None:
        with self._transaction("record an observation watermark") as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                raise self._unknown(conversation_id)
            # Both of ADR-0212 §8's conditions, read under the write lock. The
            # recorded value is the *usable* one, so a watermark this build
            # discarded (§7) is stampable again from the tail rather than leaving
            # the conversation permanently stuck behind a value nobody can read.
            recorded = _usable_watermark(row[5], row[6])
            highest = row[6]
            leads = type(highest) is not int or through_ordinal > highest
            lowers = recorded is not None and through_ordinal <= recorded
            if leads or lowers:
                # `record_delivery`'s shape and its reason: no row is written, and
                # no error is raised. An attempt that loses is an attempt whose
                # position already stands.
                return None
            conn.execute(
                "UPDATE conversations SET observed_through = ? WHERE id = ?",
                (through_ordinal, conversation_id),
            )
            stamped = self._row_of(conn, conversation_id)
            if stamped is None:  # pragma: no cover — the row was just updated here
                raise self._unknown(conversation_id)
            return stamped

    async def turns(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
        before_ordinal: int | None = None,
    ) -> list[ConversationTurn]:
        """Return a page of turns, ordinal ascending, ending below ``before_ordinal``.

        Raises:
            ValueError: If ``limit`` or ``before_ordinal`` is out of range.
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
        """
        page = self._tail_limit if limit is None else limit
        _check_page_bound("limit", page)
        if before_ordinal is not None:
            _check_page_bound("before_ordinal", before_ordinal, floor=FIRST_TURN_ORDINAL)
        async with self._lock:
            rows = await _run_to_completion(self._turns_sync, conversation_id, page, before_ordinal)
        return [self._decode_turn(row) for row in rows]

    def _turns_sync(self, conversation_id: str, page: int, before_ordinal: int | None) -> list[Any]:
        with self._transaction("read a conversation's turns", immediate=False) as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                raise self._unknown(conversation_id)
            if page == 0:
                return []
            # Take the newest `page` rows below the ceiling, then hand them back
            # oldest-first: the tail is what a continuation wants, and ordinal
            # ascending is the order it replays them in. The unbounded form is a
            # *separate* query rather than a sentinel ceiling, because there is no
            # in-range integer above every ordinal: `2**63` is one past what a
            # SQLite bind parameter can carry and raises `OverflowError`.
            head = (
                "SELECT conversation_id, ordinal, episode_id, occurred_at, execution_id, "
                "step_id, delivery_state, delivery_played, delivery_rendered "
                "FROM turns WHERE conversation_id = ?"
            )
            if before_ordinal is None:
                rows = self._fetch(
                    conn,
                    "read a conversation's turns",
                    head + " ORDER BY ordinal DESC LIMIT ?",
                    (conversation_id, page),
                )
            else:
                rows = self._fetch(
                    conn,
                    "read a conversation's turns",
                    head + " AND ordinal < ? ORDER BY ordinal DESC LIMIT ?",
                    (conversation_id, before_ordinal, page),
                )
            return list(reversed(rows))

    async def turns_after(
        self,
        conversation_id: str,
        *,
        after_ordinal: int | None = None,
        limit: int | None = None,
    ) -> list[ConversationTurn]:
        """Return the lowest page of turns above ``after_ordinal``, ordinal ascending.

        Raises:
            ValueError: If ``limit`` or ``after_ordinal`` is out of range.
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
            ConversationStoreError: If the store cannot be read.
        """
        page = self._tail_limit if limit is None else limit
        _check_page_bound("limit", page)
        if after_ordinal is not None:
            _check_page_bound("after_ordinal", after_ordinal, floor=FIRST_TURN_ORDINAL)
        async with self._lock:
            rows = await _run_to_completion(
                self._turns_after_sync, conversation_id, page, after_ordinal
            )
        return [self._decode_turn(row) for row in rows]

    def _turns_after_sync(
        self, conversation_id: str, page: int, after_ordinal: int | None
    ) -> list[Any]:
        with self._transaction("read a conversation's turns", immediate=False) as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                raise self._unknown(conversation_id)
            if page == 0:
                return []
            # `ORDER BY ordinal ASC` and no reversal afterwards: this read takes the
            # *lowest* rows above the floor rather than the newest below a ceiling,
            # which is the whole difference between it and `turns`. Both hand the
            # page back oldest-first, so the two are interchangeable to a consumer
            # that only replays what it is given.
            head = (
                "SELECT conversation_id, ordinal, episode_id, occurred_at, execution_id, "
                "step_id, delivery_state, delivery_played, delivery_rendered "
                "FROM turns WHERE conversation_id = ?"
            )
            if after_ordinal is None:
                return self._fetch(
                    conn,
                    "read a conversation's turns",
                    head + " ORDER BY ordinal ASC LIMIT ?",
                    (conversation_id, page),
                )
            return self._fetch(
                conn,
                "read a conversation's turns",
                head + " AND ordinal > ? ORDER BY ordinal ASC LIMIT ?",
                (conversation_id, after_ordinal, page),
            )

    async def episodes_to_purge(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
        after_id: str | None = None,
    ) -> list[str]:
        """Return the next batch of this conversation's episode ids, in ordinal order.

        Reads a stamped conversation *and* a live one — the deletion sweep walks
        the first, the retention reclaim the second — and removes nothing either
        way: the rows are the intent log, and they go only when
        :meth:`drop_if_eligible` succeeds.

        Raises:
            ValueError: If ``limit`` is out of range, or ``after_id`` is not an
                episode id of this conversation.
            UnknownConversationError: If the id names nothing.
        """
        batch = self._purge_batch if limit is None else limit
        _check_page_bound("limit", batch)
        async with self._lock:
            return await _run_to_completion(
                self._episodes_to_purge_sync, conversation_id, batch, after_id
            )

    def _episodes_to_purge_sync(
        self, conversation_id: str, batch: int, after_id: str | None
    ) -> list[str]:
        with self._transaction("read a conversation's episode ids", immediate=False) as conn:
            if self._row_of(conn, conversation_id) is None:
                raise self._unknown(conversation_id)
            floor = 0
            if after_id is not None:
                # The cursor is an id the caller already holds, and the store
                # places it because the encoding is its own. One it cannot place is
                # refused rather than silently restarting the walk, which would
                # make a sweep loop forever over its first batch.
                placed = self._fetch(
                    conn,
                    "place a purge cursor",
                    "SELECT ordinal FROM turns WHERE conversation_id = ? AND episode_id = ?",
                    (conversation_id, after_id),
                )
                if not placed:
                    described = describe_untrusted(after_id)
                    msg = f"after_id {described} is not an episode id of this conversation"
                    raise ValueError(msg)
                floor = _ordinal_of(placed[0][0])
            if batch == 0:
                return []
            rows = self._fetch(
                conn,
                "read a conversation's episode ids",
                "SELECT episode_id, ordinal FROM turns WHERE conversation_id = ? AND ordinal > ? "
                "ORDER BY ordinal ASC LIMIT ?",
                (conversation_id, floor, batch),
            )
            return [
                self._verified_episode_id(conversation_id, _ordinal_of(row[1]), row[0])
                for row in rows
            ]

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
            "SELECT c.id, c.started_at, c.last_active_at, c.last_turn_at, c.deleted_at, "
            "c.observed_through, (SELECT MAX(t.ordinal) FROM turns t "
            "WHERE t.conversation_id = c.id) "
            "FROM conversations c WHERE c.deleted_at IS NULL "
            "ORDER BY c.last_active_at DESC, c.id ASC LIMIT ? OFFSET ?",
            (limit, offset),
        )

    async def conversations_with_unobserved_turns(self, *, limit: int = 50) -> list[Conversation]:
        """List candidates for observation, least recently active first.

        Raises:
            ValueError: If ``limit`` is outside ``[0, 2**63)``.
            ConversationStoreError: If the store cannot be read.
        """
        _check_page_bound("limit", limit)
        if limit == 0:
            return []
        async with self._lock:
            rows = await _run_to_completion(self._unobserved_sync, limit)
        return [self._decode_conversation(row) for row in rows]

    def _unobserved_sync(self, limit: int) -> list[Any]:
        # Candidacy in four disjuncts over one subquery, which is ADR-0212 §3's rule
        # composed with §7's discard rather than either taken alone. A conversation
        # with no turn is never a candidate (`highest IS NOT NULL`); one whose stored
        # watermark this build cannot use is a candidate on its own terms, because a
        # discarded watermark reads as absent — and *that* is why the first three
        # disjuncts exist. Filtering on `t.ordinal > c.observed_through` alone would
        # get them all wrong in the same silent direction: SQLite sorts every
        # integer below every string, so a text watermark excludes the conversation
        # for good, and a REAL one excludes exactly the turns beneath it.
        return self._fetch(
            self._conn,
            "list conversations with unobserved turns",
            "SELECT id, started_at, last_active_at, last_turn_at, deleted_at, "
            "observed_through, highest FROM ("
            "SELECT c.id AS id, c.started_at AS started_at, "
            "c.last_active_at AS last_active_at, c.last_turn_at AS last_turn_at, "
            "c.deleted_at AS deleted_at, c.observed_through AS observed_through, "
            "(SELECT MAX(t.ordinal) FROM turns t WHERE t.conversation_id = c.id) AS highest "
            "FROM conversations c WHERE c.deleted_at IS NULL) "
            "WHERE highest IS NOT NULL AND ("
            "typeof(observed_through) <> 'integer' "
            "OR observed_through < ? "
            "OR observed_through > highest "
            "OR highest > observed_through) "
            "ORDER BY last_active_at ASC, id ASC LIMIT ?",
            (FIRST_TURN_ORDINAL, limit),
        )

    async def turn_of_episode(self, episode_id: str) -> ConversationTurn | None:
        """Return the turn an episode records, or ``None`` if absent or stamped.

        Raises:
            ConversationStoreError: If the turn names a conversation the store does
                not hold, or the stored row is corrupt.
        """
        async with self._lock:
            rows = await _run_to_completion(self._turn_of_episode_sync, episode_id)
        return self._presented_turn(rows)

    async def turn_of_binding(self, binding: ParkedBinding) -> ConversationTurn | None:
        """Return the turn that parked on ``binding``, or ``None`` if absent or stamped.

        Raises:
            ConversationStoreError: If the turn names a conversation the store does
                not hold, or the stored row is corrupt.
        """
        async with self._lock:
            rows = await _run_to_completion(
                self._turn_of_binding_sync, binding.execution_id, binding.step_id
            )
        return self._presented_turn(rows)

    def _turn_of_episode_sync(self, episode_id: str) -> list[Any]:
        """Resolve an episode id, carrying enough to withhold a stamped turn.

        Withholding is the whole of ADR-0074 §9's rule here: a caller holding an
        episode id from before a deletion must not get back the ordinal, timestamp
        and binding metadata every presenting read withholds. The filter is applied
        in :meth:`_presented_turn` rather than in the ``WHERE`` clause, over a
        **left** join, so that a turn naming no conversation at all is reported
        instead of being indistinguishable from a stamped one (#452).
        """
        return self._fetch(
            self._conn,
            "resolve an episode id",
            "SELECT " + _TURN_SELECT + ", c.id, c.deleted_at "
            "FROM turns t LEFT JOIN conversations c ON c.id = t.conversation_id "
            "WHERE t.episode_id = ?",
            (episode_id,),
        )

    def _turn_of_binding_sync(self, execution_id: str, step_id: str) -> list[Any]:
        """Resolve a parked binding, on the same left join for the same reason."""
        return self._fetch(
            self._conn,
            "resolve a parked binding",
            "SELECT " + _TURN_SELECT + ", c.id, c.deleted_at "
            "FROM turns t LEFT JOIN conversations c ON c.id = t.conversation_id "
            "WHERE t.execution_id = ? AND t.step_id = ?",
            (execution_id, step_id),
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
            return True

    async def drop_if_eligible(self, conversation_id: str) -> bool:
        """Remove the record and its index if it is still eligible, under the exclusion.

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
            if conversation.deleted_at is not None:
                eligible = now - conversation.deleted_at >= self._grace
            else:
                eligible = (
                    self._retention is not None
                    and now - conversation.last_active_at >= self._retention
                )
            if not eligible:
                return False
            # The index rows go first and **explicitly**, with ``ON DELETE
            # CASCADE`` behind them as a backstop rather than as the mechanism
            # (#452). ``PRAGMA foreign_keys`` is per connection and off by
            # default, so a cascade this module *relied* on would stop happening
            # on any connection that had not enabled it — and the failure mode is
            # the silent one: every drop would leave the turns behind as orphans,
            # unreachable by the very sweep that had just run. Deleting them here
            # makes the drop correct whatever the pragma says; the cascade then
            # only ever fires for a writer that is not this module.
            conn.execute("DELETE FROM turns WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            return True

    async def export(self) -> ConversationExport:
        """Return the store's own snapshot: unstamped conversations and their turns.

        No liveness filtering — this store cannot ask the ``MemoryStore`` whether
        an episode still resolves, and the user-facing export is composed in
        `orchestration` (ADR-0074 §9). Both halves are read in one deferred
        transaction, so the turns cannot describe a conversation the other half
        missed.

        Raises:
            ConversationStoreError: If the store cannot be read, a stored row is
                corrupt, or any turn names a conversation the store does not hold.
        """
        async with self._lock:
            exported_at, conversation_rows, turn_rows = await _run_to_completion(self._export_sync)
        return ConversationExport(
            exported_at=exported_at,
            conversations=tuple(self._decode_conversation(row) for row in conversation_rows),
            turns=tuple(self._decode_turn(row) for row in turn_rows),
        )

    def _export_sync(self) -> tuple[datetime, list[Any], list[Any]]:
        with self._transaction("export conversations", immediate=False) as conn:
            exported_at = self._now()
            # Probed before either half is materialised, and over the whole table
            # rather than only the rows this export would present: the snapshot is
            # the store's account of itself, so a turn naming nothing is a fault to
            # report and not a row to leave out. The query the turns are read with
            # below is an inner join and would silently drop it (#452).
            orphaned = self._fetch(
                conn,
                "export conversation turns",
                "SELECT t.conversation_id FROM turns t "
                "LEFT JOIN conversations c ON c.id = t.conversation_id "
                "WHERE c.id IS NULL LIMIT 1",
            )
            if orphaned:
                raise self._orphan(orphaned[0][0])
            conversations = self._fetch(
                conn,
                "export conversations",
                "SELECT c.id, c.started_at, c.last_active_at, c.last_turn_at, c.deleted_at, "
                "c.observed_through, (SELECT MAX(t.ordinal) FROM turns t "
                "WHERE t.conversation_id = c.id) "
                "FROM conversations c WHERE c.deleted_at IS NULL "
                "ORDER BY c.last_active_at DESC, c.id ASC",
            )
            turns = self._fetch(
                conn,
                "export conversation turns",
                "SELECT " + _TURN_SELECT + " "
                "FROM turns t JOIN conversations c ON c.id = t.conversation_id "
                "WHERE c.deleted_at IS NULL ORDER BY t.conversation_id ASC, t.ordinal ASC",
            )
            return exported_at, conversations, turns
