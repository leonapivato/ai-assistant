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
from operator import index
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pydantic import ValidationError

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import AuthorizationError, InvalidAuthorizationError
from ai_assistant.core.types import (
    Authorization,
    AuthorizationDisposition,
    AuthorizationOrigin,
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

#: The largest value SQLite will bind as an integer parameter. Binding a wider one
#: raises ``OverflowError``, which is neither ``ValueError`` nor
#: ``AuthorizationError`` — which is why ``recent`` clamps its ``limit`` and why
#: ADR-0268 §1's watermark is stored as text rather than bound as an integer at all.
_MAX_SQLITE_INT = 2**63 - 1

#: ADR-0254 §1's transition graph, whole and as data: the **seven** edges, keyed
#: by the disposition each one leaves. **Stated once**, so ``settle``'s refusal and
#: the conformance suite's enumeration cannot disagree about which moves exist. The
#: **five** dispositions absent as keys are the **retired** ones — no edge leaves
#: them, which is what ``settle`` refuses a move out of.
#:
#: **Seven since ADR-0268 §2**, which adds ``PROPOSED → GOAL_CLOSED`` and
#: ``ESTABLISHED → GOAL_CLOSED``. Both are stated here because ``settle`` *"admits
#: both like any other edge"* — the store refuses neither, and what keeps a
#: single-row settlement to ``GOAL_CLOSED`` from happening is ADR-0268 §6's writer
#: clause rather than a refusal with nowhere truthful to go.
_EDGES: Final[dict[AuthorizationDisposition, frozenset[AuthorizationDisposition]]] = {
    AuthorizationDisposition.PROPOSED: frozenset(
        {
            AuthorizationDisposition.ESTABLISHED,
            AuthorizationDisposition.DECLINED,
            AuthorizationDisposition.EXPIRED,
            AuthorizationDisposition.GOAL_CLOSED,
        }
    ),
    AuthorizationDisposition.ESTABLISHED: frozenset(
        {
            AuthorizationDisposition.REVOKED,
            AuthorizationDisposition.SUPERSEDED,
            AuthorizationDisposition.GOAL_CLOSED,
        }
    ),
}


#: The two moves that are an **answer** to the question a proposal put, and the
#: only ones on which ``settle`` performs ADR-0254 §1's expiry settlement.
#:
#: Arm 37 confines that settlement to *"a ``live_for`` read and the answer that
#: names it, **and by no other operation**"*. An approval and a refusal are the
#: two answers; a move to ``EXPIRED`` is the deadline itself and takes the ordinary
#: edge, so it is absent here rather than settled twice; and ``REVOKED`` and
#: ``SUPERSEDED`` leave ``PROPOSED`` by no edge at all, so a call asking for one is
#: not an answer and **must leave the row exactly as it stands** — otherwise a
#: refused settlement would still have mutated the store.
_ANSWERS: Final[frozenset[AuthorizationDisposition]] = frozenset(
    {AuthorizationDisposition.ESTABLISHED, AuthorizationDisposition.DECLINED}
)


def _canonical_version(goal_version: int) -> str:
    """``goal_version`` as the canonical **base-16** text this store holds it in.

    **Text and not an ``INTEGER`` column, because ADR-0268 §1's watermark is an
    unrestricted Python ``int`` and SQLite's is not.** ``Goal.version`` is
    ``int`` with ``ge=0`` and **no ceiling** (ADR-0249 §1), and ``PlanStore``
    persists a goal as JSON, which has none either — so a goal really can stand
    above ``2**63 - 1``. Bound as an integer parameter such a version raises
    ``OverflowError`` out of the driver: neither a refusal nor an
    :class:`~ai_assistant.core.errors.AuthorizationError`, and so a hole in this
    layer's boundary.

    **Refusing it instead was tried and is wrong.** A ceiling on ``goal_version``
    is a narrowing of a contract ADR-0268 states *"in full"* over an unrestricted
    ``int``, and it strands a goal rather than merely reporting: a goal at
    ``2**63 - 1`` abandons and fences successfully, its version advances, and the
    reopen's ``ACTIVE`` write then lands **before** the ending is refused —
    leaving a live goal fenced against every authorization for good. Adversarial
    and architecture review, round 2, ``blocker`` each. **So the storage widens
    and the contract does not move.**

    **``operator.index`` rather than ``int``**, so what Python itself calls an
    integer round-trips and nothing else does: ``True`` normalises to ``1``, which
    is what it *means* in Python and is therefore not a refusal; a ``float``
    raises ``TypeError`` as it would anywhere, rather than being truncated into a
    watermark the caller did not name.

    Args:
        goal_version: The version to render.

    **Base 16 and not base 10, because CPython caps decimal conversion.**
    ``str(int)`` and ``int(str)`` refuse an integer of more than
    ``sys.get_int_max_str_digits()`` digits — 4300 by default — and raise a bare
    ``ValueError`` doing it. A decimal encoding would therefore have reimposed a
    ceiling, in the same breath as this function's whole purpose is not to have one,
    and leaked that ``ValueError`` past the boundary on the way. **The limit is
    documented as applying to base 10 alone**, so ``format(…, "x")`` and
    ``int(…, 16)`` are exact at every magnitude. Adversarial review, round 3,
    ``blocker``.

    **No global is touched to get there.** ``sys.set_int_max_str_digits`` is
    process-wide, so a store raising it would be changing how every other component
    in the process renders an integer.

    Args:
        goal_version: The version to render.

    **Tagged with an ``x``, because untagged hex overlaps SQLite's own rendering.**
    The column has ``TEXT`` affinity, so an integer planted into it is stored as its
    **decimal** text — a planted ``10`` becomes ``"10"``, which is perfectly good
    untagged hexadecimal and decodes as **16**. A closure intended at version 10
    would then be held at 16, and the reopen's ``clear_closure`` at 10 would answer
    ``False`` and leave a live goal fenced for good: a *silent misread*, which is the
    one thing the exact-decode rule exists to prevent. The tag makes the two
    languages disjoint — SQLite never renders an integer with an ``x`` in it — so
    such a value is refused rather than misread. Adversarial review, round 4,
    ``blocker``; and the round-3 note claiming a planted integer round-trips was true
    of base 10 and was carried over to base 16 without rechecking, which is why it
    only held for ``0``-``9``.

    Args:
        goal_version: The version to render.

    Returns:
        Its canonical tagged base-16 text — ``x`` then lowercase hex digits, no
        leading zeros, no padding, a leading ``-`` before the tag where negative.

    Raises:
        TypeError: If ``goal_version`` is not an integer by Python's own test.
    """
    normalised = index(goal_version)
    sign = "-" if normalised < 0 else ""
    return f"{sign}x{abs(normalised):x}"


def _decoded_version(raw: object, goal: str, path: str) -> int:
    """One stored watermark, or refuse the record as corrupt (ADR-0268 §1).

    **Base-16 canonical text** (:func:`_canonical_version`).

    **Validated exactly rather than coerced**, and the reason is the invariant:
    the watermark is one *"neither member lowers"*, so a value read back as
    anything but what was written can lower it silently. A column read with
    ``int(…)`` would take a planted ``4.5`` as version **4** — SQLite stores what
    it is given whatever a column is declared as — and an ``end_for_goal`` at 4
    would then proceed and rewrite the record down to 4; a planted ``'abc'``
    would leak a raw ``ValueError`` past this layer's boundary. Adversarial
    review, round 2, ``major``.

    The table's own ``CHECK`` refuses both at the write, so this is the second
    line and covers a file this store did not write.

    Args:
        raw: The column's value, as SQLite returned it.
        goal: Whose record it is, for the message.
        path: The database's path, for the message.

    Returns:
        The watermark.

    Raises:
        AuthorizationError: If the stored value is not canonical base-16 text.
            **Nothing is mutated on the way out**, the read happening inside the
            caller's transaction and before any write.
    """
    if isinstance(raw, str):
        negative = raw.startswith("-")
        body = raw[1:] if negative else raw
        if body.startswith("x") and _is_hex(body[1:]):
            value = -int(body[1:], 16) if negative else int(body[1:], 16)
            # **The round-trip is the exact test**, and it is what refuses a second
            # spelling of one number: ``x007``, ``-x0`` and ``x`` alone all decode
            # and none of them is what this store writes.
            if _canonical_version(value) == raw:
                return value
    msg = (
        f"the authorization store at {path!r} holds a closure record for goal "
        f"{goal!r} whose version is {describe_untrusted(raw)} rather than canonical "
        f"tagged base-16 text (x1f, -x1f); the watermark is never lowered, so a "
        f"record that cannot be read exactly is not read at all (ADR-0268 §1)"
    )
    raise AuthorizationError(msg)


def _is_hex(body: str) -> bool:
    """Whether ``body`` is a non-empty run of lowercase hex digits and nothing else.

    Written out rather than left to ``int(body, 16)``, which accepts an ``0x``
    prefix, underscores, surrounding whitespace, uppercase and Unicode digit forms
    — so several spellings of one number would decode and only one would compare
    equal to what was written. The round-trip in the caller is what makes the test
    exact; this is what keeps ``int`` from being handed something surprising first.
    """
    return bool(body) and all(character in "0123456789abcdef" for character in body)


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


#: **Two shapes.** Version 1 held the rows alone; version 2 adds ADR-0268 §1's
#: per-goal **closure record**.
#:
#: **The migration is structural and nothing more** (ADR-0268 §9): a version-1
#: database opens under version 2 with *every row it held intact*, the upgrade
#: **creates the closure-record storage and moves the marker**, and that is the
#: whole of it. **No row is rewritten, re-dispositioned or back-filled and no goal
#: is recorded closed by the upgrade** — so a database written before that decision
#: may hold an ``ESTABLISHED`` row whose goal was already closed, and it stands
#: until its own ``expires_at`` exactly as it did before. That is the prospectivity
#: bound stated rather than implied, and it is *no worse than the pre-decision
#: behaviour*; the one path by which such a row could outlive that bound is closed
#: by §2's reopen, which ends it before clearing the fence.
#:
#: **Nothing reads ``PlanStore`` at the upgrade to find out which goals closed.**
#: That cross-store read is the subsystem-boundary crossing ADR-0268 §1 declines at
#: the *write*, and declining it at the write while taking it at the upgrade would
#: put the same read in the same place by another door. **No back-fill, no
#: reconciliation pass, no start-up scan, no compatibility shim, no lenient decode
#: and no tolerated-unknown entry.**
#:
#: **Why the creates are unconditional rather than a version-keyed ``_migrate``.**
#: Every object this store defines is created with ``IF NOT EXISTS`` and then held
#: to its own definition (:data:`_OBJECTS`), so the upgrade *is* the ordinary setup
#: path running against a file that lacks one table — and a version-keyed branch
#: would be a second statement of which objects version 2 has, free to drift from
#: the first.
_SCHEMA_VERSION = 2

#: Created first and on its own, so a database labelled with a schema this code
#: cannot read is refused *before* the ``goal_authorizations`` table is created or
#: read — creating a table is a write, and the refusal precedes any write.
_META_SCHEMA = "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"

_READ_SCHEMA_VERSION = "SELECT value FROM meta WHERE key = 'schema_version'"

#: **An upsert, because the marker now *moves*.** Version 1 only ever stamped an
#: unlabelled file, so a plain ``INSERT`` sufficed; ADR-0268 §9 has a version-1
#: database open under version 2, and its ``meta`` row already exists.
_WRITE_SCHEMA_VERSION = (
    "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
    "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
)

#: Every ``schema_version`` this code can open. **A file below the current version
#: is upgraded; one above it is refused**, because a newer writer may have written
#: rows this code would decode wrongly — ADR-0039 §10's mechanism, and the reason
#: no lenient decode is added.
_READABLE_SCHEMA_VERSIONS: Final[frozenset[int]] = frozenset({1, _SCHEMA_VERSION})

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

#: **ADR-0268 §1's closure record — one row per goal, a watermark and a fence.**
#:
#: ``goal`` is the primary key, which is what makes it *one per goal*. ``version``
#: is the watermark **neither member lowers and neither removes**, and ``fenced``
#: is whether this store admits a row of that goal — raised by ``end_for_goal``,
#: **lifted rather than removed** by ``clear_closure``. Stored as an ``INTEGER``
#: because SQLite has no boolean, and constrained to ``0``/``1`` so a hand-built
#: file cannot make the fence read as a third thing.
#:
#: **It carries no basis, no instant, no expiry and no disposition**: it is neither
#: an authority, nor coverage, nor a row, which is why ``export`` does not reach it
#: and why ``clear`` — and only ``clear`` — erases it (§1).
#:
#: **Plain columns, not generated ones.** The rows' four projections are generated
#: from the blob because a stored copy of a value a uniqueness check reads could
#: disagree with the record it describes (below); there is no blob here and nothing
#: to disagree with, the record being exactly these three values.
#:
#: **``version`` is canonical base-16 TEXT and not an ``INTEGER``**, and the reason
#: is ADR-0268 §1's own domain: ``Goal.version`` is an ``int`` with ``ge=0`` and no
#: ceiling, and a goal above ``2**63 - 1`` is one this store must be able to fence.
#: See :func:`_canonical_version` for why the alternative — refusing such a version —
#: strands the goal rather than reporting anything.
#:
#: **The ``CHECK`` pins the stored form, because SQLite stores what it is given.** A
#: declared type is an *affinity* rather than a constraint: an ``INTEGER`` column
#: accepts ``4.5`` and ``'abc'`` alike, and a watermark read back as ``4`` from a
#: planted ``4.5`` is one a later call can silently **lower** — the one thing the
#: record is for. ``typeof`` pins the storage class and the ``GLOB`` pins the
#: characters; :func:`_decoded_version` then pins the exact value on the way out, so
#: a file this store did not write is refused rather than misread.
#:
#: **Tagged base 16** (``x1f``, ``-x1f``), because CPython caps *decimal* integer
#: conversion at 4300 digits — so a base-10 encoding would have reimposed the very
#: ceiling this column exists not to have — and because untagged hex **overlaps
#: SQLite's own rendering**: a planted integer ``10`` is stored by this column's
#: ``TEXT`` affinity as ``"10"``, which is good untagged hex for **16**. The tag
#: makes the two languages disjoint, so such a value is refused rather than misread
#: (:func:`_canonical_version`).
_CREATE_CLOSURES = (
    "CREATE TABLE IF NOT EXISTS goal_authorization_closures("
    "goal TEXT PRIMARY KEY NOT NULL, "
    "version TEXT NOT NULL CHECK ("
    "typeof(version) = 'text' AND version NOT GLOB '*[^0-9a-fx-]*' "
    "AND (version GLOB 'x[0-9a-f]*' OR version GLOB '-x[0-9a-f]*') "
    "AND version NOT GLOB '?*x*x*'), "
    "fenced INTEGER NOT NULL CHECK (fenced IN (0, 1)))"
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
    "goal_authorization_closures": _CREATE_CLOSURES,
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

#: One goal's closure record, or nothing.
_CLOSURE_OF_GOAL = "SELECT version, fenced FROM goal_authorization_closures WHERE goal = ?"

#: Raise or lift one goal's record. **Upsert rather than delete-and-insert**,
#: because a record is *lifted and never removed* and the two statements would be a
#: window in which neither stood.
_WRITE_CLOSURE = (
    "INSERT INTO goal_authorization_closures(goal, version, fenced) VALUES (?, ?, ?) "
    "ON CONFLICT(goal) DO UPDATE SET version = excluded.version, fenced = excluded.fenced"
)

#: Every row of one goal standing ``PROPOSED`` or ``ESTABLISHED`` — exactly the set
#: ``end_for_goal`` ends. **No instant appears in it**: that member *evaluates no
#: liveness*, so a lapsed proposal is in this set like any other.
_STANDING_OF_GOAL = (
    "SELECT data FROM goal_authorizations WHERE goal = ? AND disposition IN (?, ?) "
    "ORDER BY proposed_at_us DESC, id ASC"
)


def _checked_target(to: AuthorizationDisposition) -> None:
    """Hold ``to`` to the exact member before any settlement branches on it.

    **The annotation is the contract** — ADR-0254 §16 signs ``settle`` with
    ``to: AuthorizationDisposition``, and ``mypy --strict`` runs over ``src`` and
    ``tests``, so every caller in this tree is already held to it. This is the
    guard for the one caller a type cannot reach, which is
    :meth:`SqliteGoalAuthorizationStore.recent`'s own ground for its ``limit``
    allowlist: *"reachable only from untyped code"*.

    **It refuses rather than normalising, and the direction is the point.** A
    ``StrEnum`` member's own value is **equal** to it and is not **identical** to
    it, and a settlement asks both questions — *"is this an edge"* against a
    ``frozenset`` of members, by equality; *"is this the establishment"* against one
    member, by identity. A ``"established"`` reaching from untyped code passes the
    first and fails the second, taking the direct write and skipping ADR-0254 §1's
    uniqueness check entirely: **two ``ESTABLISHED`` rows of one pair, which is the
    state §1 forbids.** Refusing closes that at the door and is strictly **narrower**
    than the ratified signature; coercing the value would have widened what the
    contract admits, which is a change to it rather than an implementation of it
    (golden rule 5).

    **An allowlist of the exact type**, which is
    :meth:`SqliteGoalAuthorizationStore.recent`'s own shape for its ``limit`` and
    ``core.config``'s for an integer setting (issue #471): *"every value this
    refuses … is precisely an ``isinstance`` match"*. Here the match is the other
    way round and the exact test is what a narrowing type checker leaves
    reachable — an ``Enum`` with members cannot be subclassed, so exact-type and
    membership are the same set and nothing conforming is refused by it.

    Raises:
        ValueError: If ``to`` is not an ``AuthorizationDisposition`` member. The
            untrusted value is described through
            :func:`~ai_assistant.core.types.describe_untrusted` rather than
            ``repr``, so a hostile ``__repr__`` cannot replace the documented
            refusal with its own exception.
    """
    if type(to) is not AuthorizationDisposition:
        msg = (
            f"to must be an AuthorizationDisposition member, got "
            f"{describe_untrusted(to)}; a settlement asks which member it is by both "
            f"equality and identity, and a value that answers those differently skips "
            f"the uniqueness check (ADR-0254 §1, §16)"
        )
        raise ValueError(msg)


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


def _money_narrows(later: ValueBound, earlier: ValueBound) -> bool:
    """ADR-0254 §5's non-widening test over two ``MONEY`` bounds.

    **Extracted so the ceiling's two facts are read together** (ADR-0266 §3): the
    figure and whether the endpoint itself is permitted are one statement about what
    the user allowed, and a comparison that read only the figure would admit a
    correction that adds back the call the live row refused.
    """
    # A ``None`` on either side is unreachable — the model requires a ``MONEY``
    # bound's ``currency`` and ``maximum`` — and the narrowing question is answered
    # ``False`` for one all the same, which is the fail-closed direction and costs a
    # confirmation rather than an assertion.
    if later.currency != earlier.currency:
        return False
    if later.maximum is None or earlier.maximum is None or later.maximum > earlier.maximum:
        return False
    # **At an equal ceiling the flag is the whole of the difference** (ADR-0266 §3):
    # clearing it admits a call at exactly the endpoint the live row refused, which
    # is a widening however the two numbers compare.
    if (
        later.maximum == earlier.maximum
        and earlier.maximum_exclusive
        and not later.maximum_exclusive
    ):
        return False
    # A lower bound the correction **drops** widens: every amount below the earlier
    # minimum becomes permitted. One it **adds** narrows, and one it raises narrows;
    # one it lowers widens.
    if earlier.minimum is None:
        return True
    return later.minimum is not None and later.minimum >= earlier.minimum


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
    change of ``currency`` or of a ``PERIOD``'s ``timezone``: each re-denominates
    what the bound is *about* rather than shrinking what it permits, so each takes
    path (i) and is confirmed.

    **``maximum_exclusive`` is ordered rather than compared numerically** (ADR-0266
    §3). At an **equal** ``maximum`` the flag is the whole of the difference:
    **setting** it narrows — *"at most 100"* corrected to *"under 100"* withdraws
    the endpoint — and **clearing** it **widens**, adding a call at exactly the
    ceiling that the live row refused. So a clearing at an equal ``maximum`` is a
    widening ADR-0254 §5 refuses: path (ii) writes no row, and the act asks and is
    established by path (i) carrying ``supersedes``. A lane that compared
    ``maximum`` alone would read it as no change and establish a wider authority
    with no confirmation.

    Args:
        later: The correcting row's bound for this kind.
        earlier: The superseded row's bound of the same kind.

    Returns:
        Whether every value ``later`` permits ``earlier`` permits too.
    """
    if later.kind is not earlier.kind:
        return False
    if later.kind is BoundKind.MONEY:
        return _money_narrows(later, earlier)
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
    **kind** (ADR-0266 §3, which is what now identifies a member), with §9 clause
    (ii)'s principle as the whole of the reason: **the interpretation narrows what
    the act covers and can never widen it**.

    * A member of a kind the superseded row carries none of is an **addition**,
      refused.
    * A member **byte-identical** to the superseded row's is carried forward, and
      that is the ordinary case for every argument the correction does not touch —
      its own basis included, so the record says which act each value came from.
    * A member that **replaces a fixed value** of a kind the superseded row already
      fixed is admitted, whatever the new value: this is *"make it Sunday"*, and the
      act that states it is itself recorded.
    * A member that **narrows a bound** of a kind the superseded row already bounded
      is admitted; one that widens it is refused. **A bound of a different kind
      cannot arise**, a member and its bound now agreeing by construction.
    * A member that turns a fixed value into a bound, or a bound into a fixed
      value, is **neither** of those two motions and is refused: it does not
      replace a value for an argument the row *fixed*, and it does not narrow a
      bound for one the row *bounded*.

    Args:
        later: The correcting row's member.
        earlier: The superseded row's member of the same kind, or ``None`` where it
            carries none.

    Returns:
        The refusal's reason, or ``None`` where the member is a permitted
        correction.
    """
    key = later.kind.value
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
                stored = self._check_schema_version(conn)
                conn.execute(_CREATE_TABLE)
                # The table is held to its definition **before** the indexes and the
                # trigger are created over it, so a file arriving with a
                # ``goal_authorizations`` table of ordinary columns is reported as
                # what it is rather than as an index failing on a column it lacks.
                self._check_objects(conn, ("goal_authorizations",))
                for statement in _INDEXES.values():
                    conn.execute(statement)
                conn.execute(_SETTLE_ONLY)
                # **ADR-0268 §9's migration, and the whole of it.** On a version-1
                # file this is the create that upgrades it; on a version-2 file it
                # is a no-op. Nothing else happens either way: no row is rewritten,
                # re-dispositioned or back-filled, and no goal is recorded closed —
                # *"a lane that moved the marker without creating the storage has
                # shipped a store no existing database opens"*, and one that
                # rewrote a row would have retrofitted a decision that governs
                # closing acts taken after it ships.
                conn.execute(_CREATE_CLOSURES)
                self._check_objects(conn, tuple(_OBJECTS))
                if stored != _SCHEMA_VERSION:
                    # Stamped *after* the creates and inside the same transaction, so
                    # a failure rolls the marker — and the `meta` table itself — back
                    # rather than leaving a database falsely labelled current. The
                    # same write serves both cases: an unlabelled file is stamped,
                    # and a version-1 file has its marker **moved** once the storage
                    # the new version means exists beside it.
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

    def _check_schema_version(self, conn: sqlite3.Connection) -> int | None:
        """Refuse a labelled schema this code cannot read; say which one is labelled.

        Runs inside the setup transaction, after ``meta`` exists and **before** the
        ``goal_authorizations`` table is created or read. An **unlabelled** database
        is one this code is creating now and is stamped rather than migrated; a
        **version-1** one is upgraded, which ADR-0268 §9 makes *structural and
        nothing more* — the setup's own creates add the closure-record storage and
        the marker is then moved, with every row it held left byte for byte as it
        was.

        Returns:
            The version the database carries, or ``None`` where it carries none.

        Raises:
            AuthorizationError: If the stored version is not one this code
                understands, is not an integer at all, or is not a single
                unambiguous value.
        """
        rows = conn.execute(_READ_SCHEMA_VERSION).fetchall()
        if not rows:
            return None
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
        if stored not in _READABLE_SCHEMA_VERSIONS:
            supported = ", ".join(str(one) for one in sorted(_READABLE_SCHEMA_VERSIONS))
            msg = (
                f"the authorization store at {self._path!r} has schema_version={stored}, "
                f"but this code supports only version {supported}; refusing to open "
                f"it rather than read it blindly"
            )
            raise AuthorizationError(msg)
        return stored

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
            self._check_not_fenced(conn, snapshot)
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

        **And the origin a path determines is the one the row must carry**, because
        ``origin`` is what route (d) reads to decide whether to re-take the recipient
        authority an opening act rested on (§1, §6) — *"read off the row, with no
        store read and no walk back through a chain"*. Two of the three paths
        determine it outright: a row naming a ``confirmation`` is path (i) and is
        ``CONFIRMED``, *"because the destination set is named in the question the
        user answers"*; a row naming neither pointer is path (iii) and is
        ``OPENING_ACT``. The third — a correction — **transcribes** it, which
        :meth:`_check_correction` is what holds.

        Raises:
            InvalidAuthorizationError: If a row carrying ``confirmation`` is written
                in any disposition but ``PROPOSED`` or with an origin other than
                ``CONFIRMED``; if a row carrying neither pointer carries an origin
                other than ``OPENING_ACT``; or if a row carrying ``confirmation``
                unset is written in any disposition but ``ESTABLISHED`` or with
                ``settled_at`` unequal to ``proposed_at``.
        """
        if row.confirmation is not None:
            if row.disposition is not AuthorizationDisposition.PROPOSED:
                msg = (
                    f"authorization {row.id!r} names a confirmation, so it is written "
                    f"PROPOSED and reaches every later disposition through settle alone; "
                    f"it was written {row.disposition} (ADR-0254 §1)"
                )
                raise InvalidAuthorizationError(msg)
            if row.origin is not AuthorizationOrigin.CONFIRMED:
                msg = (
                    f"authorization {row.id!r} names a confirmation, so its origin is "
                    f"CONFIRMED — the destination set is named in the question the user "
                    f"answers — and it was written {row.origin} (ADR-0254 §1)"
                )
                raise InvalidAuthorizationError(msg)
            return
        if row.supersedes is None and row.origin is not AuthorizationOrigin.OPENING_ACT:
            # **The one row shape whose origin is fully determined by its pointers**,
            # and the one whose origin route (d) reads to decide whether to re-take
            # the recipient authority it rested on (§1, §6). A path-(iii) row marked
            # CONFIRMED would let route (d) carry an opening act **alone**, with the
            # grant seam consulted zero times — which is the failure arm 70 names:
            # "a lane that wrote an opening-act row and then let route (d) carry it
            # alone fails this arm". Every other origin is either determined here or
            # transcribed from the row a correction supersedes.
            msg = (
                f"authorization {row.id!r} names neither a confirmation nor a row it "
                f"supersedes, so it records an opening act and its origin is "
                f"OPENING_ACT; it was written {row.origin} (ADR-0254 §1)"
            )
            raise InvalidAuthorizationError(msg)
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
        held = {member.kind: member for member in earlier.coverage}
        for member in row.coverage:
            defect = _member_defect(member, held.get(member.kind))
            if defect is not None:
                msg = (
                    f"authorization {row.id!r} corrects {earlier.id!r}: {defect} (ADR-0254 §1, §9)"
                )
                raise InvalidAuthorizationError(msg)
        dropped = sorted(
            kind.value for kind in held.keys() - {member.kind for member in row.coverage}
        )
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

    def _check_not_fenced(self, conn: sqlite3.Connection, row: Authorization) -> None:
        """Refuse a row whose goal this store holds fenced (ADR-0268 §1).

        Read **inside** ``record``'s own ``BEGIN IMMEDIATE`` transaction, which is
        what makes the refusal *"decided in the same indivisible step as the
        write"*: the write lock is already held, so no ``end_for_goal`` can raise a
        fence between this read and the insert, and none can be lifted between them
        either.

        **Taken before the path rules and the uniqueness checks**, so a row of a
        fenced goal is reported as what it is rather than as whichever other rule it
        happens to trip first.

        Args:
            conn: The connection ``record``'s transaction is running on.
            row: The row being written.

        Raises:
            InvalidAuthorizationError: If the row's goal stands fenced. **The class
                is reused and none is minted** — ADR-0254 §16 gives it *"a write
                this store does not admit"*.
        """
        found = conn.execute(_CLOSURE_OF_GOAL, (row.goal,)).fetchone()
        if found is None or not int(found[1]):
            return
        standing = _decoded_version(found[0], row.goal, self._path)
        # **Named base 16**, as it is stored and for the same reason: ``str(int)``
        # refuses an integer of more than ``sys.get_int_max_str_digits()`` decimal
        # digits, so rendering the version in decimal would raise while building the
        # message for a version this store holds perfectly well.
        msg = (
            f"authorization {row.id!r} names goal {row.goal!r}, which this store holds "
            f"fenced at version 0x{standing:x} by the ending its closure took; no row "
            f"of it comes into being while that fence stands (ADR-0268 §1)"
        )
        raise InvalidAuthorizationError(msg)

    # --- the ending -------------------------------------------------------

    async def end_for_goal(self, goal: str, /, *, at: datetime, goal_version: int) -> int:
        """End every standing authorization of ``goal`` and fence it (ADR-0268 §1).

        **One indivisible step** — one ``BEGIN IMMEDIATE`` transaction — over the
        staleness test, the settlements and the record, so no interleaving leaves a
        partition of the rows it saw and none admits a row of that goal after it
        returns.

        **It reads no clock**: ``at`` is the caller's, and is the act's own instant
        read once (ADR-0254 §16's discipline for ``record`` and ``settle`` alike).
        **It evaluates no liveness**, so a lapsed ``PROPOSED`` row is settled
        ``GOAL_CLOSED`` and not ``EXPIRED``. And it edits each row's ``disposition``
        and ``settled_at`` and nothing else, so the settlement trigger governs this
        write unchanged and no ``expires_at`` moves.

        Returns:
            How many rows this step moved.

        Raises:
            TypeError: If ``goal_version`` is not an integer by Python's own test
                (:func:`_canonical_version`). **No ceiling is imposed**: the
                watermark is stored as canonical base-16 text, so the whole
                ``Goal.version`` domain round-trips, at every magnitude.
            AuthorizationError: If the store cannot be read or written, **or holds a
                closure record whose version is not canonical base-16 text**, which
                is refused rather than misread (:func:`_decoded_version`). The step
                is
                all-or-nothing: the transaction rolls back, so nothing is settled
                and no record is raised.
        """
        # **Normalised before any I/O**, so a value that is not an integer is
        # Python's own ``TypeError`` at the call rather than a fault from somewhere
        # inside a transaction — and so the answer does not depend on whether a
        # record happens to exist, which an early return would otherwise decide.
        normalised = index(goal_version)
        async with self._lock:
            return await _run_to_completion(self._end_for_goal_sync, goal, at, normalised)

    def _end_for_goal_sync(self, goal: str, at: datetime, goal_version: int) -> int:
        """Settle the goal's standing rows and raise its record, as one transaction."""
        with self._transaction(f"end the authorizations of goal {goal!r}") as conn:
            found = conn.execute(_CLOSURE_OF_GOAL, (goal,)).fetchone()
            if found is not None and _decoded_version(found[0], goal, self._path) > goal_version:
                # **The stale-call rule** (§1). A record standing above this version
                # means some act read the goal above it, so this attempt's own
                # closing write is refused stale anyway — and the rows it would have
                # ended are of a request established after its read, which it never
                # had an authority over. **The version governs staleness, never
                # emptiness**: nothing here is conditioned on the row set.
                return 0
            rows = conn.execute(
                _STANDING_OF_GOAL,
                (
                    goal,
                    AuthorizationDisposition.PROPOSED.value,
                    AuthorizationDisposition.ESTABLISHED.value,
                ),
            ).fetchall()
            for row in rows:
                self._write_settlement(
                    conn,
                    _decode(str(row[0])),
                    to=AuthorizationDisposition.GOAL_CLOSED,
                    settled_at=at,
                )
            conn.execute(_WRITE_CLOSURE, (goal, _canonical_version(goal_version), 1))
            return len(rows)

    async def clear_closure(self, goal: str, /, *, goal_version: int) -> bool:
        """Lift ``goal``'s write fence, removing no record (ADR-0268 §1).

        **Settles nothing, revives nothing and reads no clock.** A row already
        ``GOAL_CLOSED`` is retired and no edge leaves it, so nothing here restores
        one.

        Returns:
            Whether a **standing** fence was lifted — ``False`` where it was already
            lifted, where the record stands at a higher version, and where the store
            holds no record of that goal.

        Raises:
            TypeError: If ``goal_version`` is not an integer by Python's own test
                (:func:`_canonical_version`). **No ceiling is imposed.**
            AuthorizationError: If the store cannot be read or written, **or holds a
                closure record whose version is not canonical base-16 text**
                (:func:`_decoded_version`).
        """
        normalised = index(goal_version)
        async with self._lock:
            return await _run_to_completion(self._clear_closure_sync, goal, normalised)

    def _clear_closure_sync(self, goal: str, goal_version: int) -> bool:
        """Raise the record with the fence down, or leave it be, as one transaction."""
        with self._transaction(f"clear the closure fence of goal {goal!r}") as conn:
            found = conn.execute(_CLOSURE_OF_GOAL, (goal,)).fetchone()
            if found is None or _decoded_version(found[0], goal, self._path) > goal_version:
                # **A goal the store holds no record of is answered ``False``, has
                # none written and raises nothing**, and a record standing at a
                # higher version is left exactly as it was — which is what keeps a
                # stale caller from unfencing a later closure (§1).
                return False
            conn.execute(_WRITE_CLOSURE, (goal, _canonical_version(goal_version), 0))
            # **The record is raised whichever way this answers**: the watermark
            # moves on a record already lifted at a lower version too, which is what
            # makes a delayed ``end_for_goal`` at that lower version answer ``0``.
            return bool(int(found[1]))

    # --- the write path, continued ----------------------------------------

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

        **``to`` is held to the exact member before anything branches on it**
        (:func:`_checked_target`), and the reason is that this method asks *"which
        member is this"* twice, in two ways: the edge lookup compares by
        **equality** and the establishment branch by **identity**.

        Raises:
            ValueError: If ``to`` is not a member of
                :class:`~ai_assistant.core.types.AuthorizationDisposition`. Refused
                **locally and before any I/O** — before the lock, before the
                connection and before any scripted fault a double could raise — so
                the guard cannot be sequenced behind a store's own failure.
            AuthorizationError: If the store cannot be read or written. **A refusal
                is not this**: the four outcomes are total over what the step can
                answer, and a refusal that raised would make one an exception.
        """
        _checked_target(to)
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
            # The expiry settlement is taken **first**, and only where this call is
            # an **answer** (:data:`_ANSWERS`): arm 37 confines it to *"a ``live_for``
            # read and the answer that names it, **and by no other operation**"*.
            held = self._expired_first(conn, stored, settled_at) if to in _ANSWERS else stored
            if to is AuthorizationDisposition.EXPIRED and settled_at < held.expires_at:
                # **``PROPOSED → EXPIRED`` is "the deadline passed before an answer"**
                # (§1's graph, stated with the edge), so the source of that edge is a
                # proposal **whose deadline has passed** — and a row whose deadline has
                # not is not standing at it. Settling one ``EXPIRED`` early would record
                # a false fact the store can see is false, from two recorded values and
                # no clock: a row saying it lapsed at 10:00 while carrying an
                # ``expires_at`` of 21:00, which ``recent`` and ``export`` then render as
                # a question that expired. §1 keeps that member apart from every other
                # precisely so a listing can tell them apart.
                return AuthorizationSettlement.NOT_AT_SOURCE
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

        **The closure records go with the rows** (ADR-0268 §1): a record is keyed by
        a goal identifier, a goal identifier is Tier-1 user data, and one surviving
        a wholesale erasure would be a retained identifier of a user who asked for
        everything to be forgotten. **A record whose fence is lifted goes exactly as
        a standing one does**, and this is the only thing that erases either — there
        is no ``delete(goal)`` for one any more than there is a ``delete(id)`` for a
        row. **The count answered is of rows and is unchanged**, a record being no
        row.

        So ADR-0268 §1's universal — no row of a closed goal stands and none can be
        recorded — holds *absent a ``clear``*, and afterwards a turn that read the
        goal open before the closure can record a row under it. That is the stated
        cost, and the alternative is worse in the direction that matters: the only
        fix is retaining the goal identifiers of a cleared store.

        Only ``goal_authorizations`` and ``goal_authorization_closures`` are
        emptied: the ``meta`` schema marker describes the file's shape rather than
        the user's history, so burning the book leaves a database this code can
        still open. Nothing else is retained — no id, no tombstone, no derived value
        — so an id held before this may be recorded again afterwards.
        """
        with self._transaction("clear the authorization store") as conn:
            removed = conn.execute("DELETE FROM goal_authorizations").rowcount
            # **Inside the same transaction as the rows**, so no reader sees a store
            # emptied of rows while a fence of it still stands.
            conn.execute("DELETE FROM goal_authorization_closures")
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
