"""One parked-read store, and one set of operations over it (ADR-0244 §18's Lane 2).

ADR-0244 §18 names four of this decision's rulings as ones that are "deliberately not
suite clauses, and putting them there would be the error", the fourth being **that the
composition root wires one instance**: "a generic conformance suite cannot see a wiring
or the absence of a call; each is a property of a call site and is asserted by a
representative test where that site is". This is that test, and this file is where that
site is.

**There is no type that could say it.** Every seam below is annotated ``ParkedReads`` or
``ParkedReadOperations``, so a root that built a second store, or a second operations
object over the same store, type-checks exactly as this one does and passes every other
case in ``tests/app/``. What the identity buys is what ADR-0244 §3 turns on: the
one-open-park rule, the one-park-per-decision rule and the settle-once gate are the
**store's** invariants, so two stores over two files would each hold all three about its
own rows and none about the other's — a park written by the servicing that the
enumeration could not find, and a token answered against a park nothing holds.

**Nothing here opens a socket.** Every case builds the engine over a hashing embedder and
closes it; the deployment that connects a search account names an ``.invalid`` origin
(RFC 6761 §6.4) and no transport is ever driven.
"""

from __future__ import annotations

import sqlite3
import stat
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.permissions.parked_reads import SqliteParkedReads

if TYPE_CHECKING:
    from pathlib import Path

#: The account a configured deployment names. ``.invalid`` (RFC 6761 §6.4).
CONNECTION: Final = "conn-0001"
SEARCH_ORIGIN: Final = "https://search.example.invalid"


def _settings(*, configured: bool) -> Settings:
    """Settings for a deployment that has, or has not, connected a search account."""
    if not configured:
        return Settings(embedder=EmbedderKind.HASHING)
    return Settings(
        embedder=EmbedderKind.HASHING,
        web_search_connection=CONNECTION,
        web_search_origin=SEARCH_ORIGIN,
    )


async def test_one_store_reaches_the_servicing_site_the_operations_and_the_lifecycle(
    tmp_path: Path,
) -> None:
    """ADR-0244 §18's fourth ruling: **the composition root wires one instance**.

    The three holders are the three things a park's life passes through — the servicing
    that writes it (§1), the operations that enumerate, answer and cancel it (§5, §6,
    §11), and the capture/lifecycle stage that drops a deleted conversation's (§3) — and
    the identity is asserted rather than the type, because the type is satisfied by any
    number of stores.

    A second store here is not a subtle fault: the servicing would write a park into one
    file, ``pending_confirmations`` would enumerate the other and offer nothing, and a
    conversation's deletion would destroy the parks of a store no question was ever
    written into.
    """
    engine = build_engine(_settings(configured=True), data_dir=tmp_path)
    try:
        servicer = engine._loop._search
        assert servicer is not None, "a configured deployment services searches"
        operations = engine._parked_reads
        assert operations is not None, "and holds the operations over its parks"

        assert isinstance(servicer._parked_reads, SqliteParkedReads), "the durable store"
        assert operations._store is servicer._parked_reads
        assert engine._conversations._parked_reads is servicer._parked_reads
    finally:
        await engine.aclose()


async def test_one_operations_object_reaches_the_engine_and_the_establishing_act(
    tmp_path: Path,
) -> None:
    """The same ruling one layer up, and it is what makes ADR-0235 §3's eighth
    condition true of this deployment.

    ADR-0244 §5 adds an eighth availability condition to the establishing act — the
    decision's id is not named by a park whose disposition is ``OPEN``, ``APPROVED`` or
    ``DENIED`` — and ``RecipientGrantOperations`` decides it from ``park_of_decision``.
    Wired to a *second* operations object, the two would each answer honestly about
    their own dispatches and disagree about which reads are in flight, which is §11's
    ``INTERRUPTED``/``NOTHING_TO_CANCEL`` split reduced to a coin toss; wired to none,
    the condition would exclude nothing and the act could resolve a ``CONFIRM`` a park
    had already taken the answer to.
    """
    engine = build_engine(_settings(configured=True), data_dir=tmp_path)
    try:
        operations = engine._parked_reads
        assert operations is not None
        assert engine._recipient_grants._parked_reads is operations
    finally:
        await engine.aclose()


async def test_the_operations_dispatch_through_the_very_servicer_that_parks(
    tmp_path: Path,
) -> None:
    """ADR-0244 §7: approval runs that exact read, by the route ADR-0231 §6 already fixed.

    A second ``SearchServicer`` would hold a second query composer, a second view of the
    per-conversation budget and a second binding seam — so the read dispatched on the
    user's *yes* would be ruled and bound by an object that never saw the question.
    """
    engine = build_engine(_settings(configured=True), data_dir=tmp_path)
    try:
        operations = engine._parked_reads
        assert operations is not None
        assert operations._search is engine._loop._search
        # And the conversation index is the one the capture stage and the footing hold,
        # which is ADR-0238 §8's single-instance obligation reaching a third consumer.
        assert operations._conversations is engine._conversations._conversations
    finally:
        await engine.aclose()


async def test_a_deployment_that_connected_no_account_still_opens_the_store(
    tmp_path: Path,
) -> None:
    """The store is built unconditionally, and the servicer is not.

    ADR-0238 §14's reasoning for the store one module over, applied here: a file created,
    opened and closed on every start from the first release that carries the contract is
    a schema nobody has to migrate on the day a consumer needs it. The operations over it
    are wired too, and answer what is true of a deployment that can service no search:
    an empty enumeration, and an answer that reaches the dispatch is ``UNAVAILABLE_NOW``.
    """
    engine = build_engine(_settings(configured=False), data_dir=tmp_path)
    try:
        assert engine._loop._search is None, "no account, no servicer"
        operations = engine._parked_reads
        assert operations is not None
        assert operations._search is None
        assert isinstance(operations._store, SqliteParkedReads)
        assert await operations.outstanding() == ()
    finally:
        await engine.aclose()

    assert (tmp_path / "parked_reads.db").exists()


async def test_the_stores_file_is_owner_only_where_the_root_put_it(tmp_path: Path) -> None:
    """ADR-0004 §2's residency clause and §4's mode, at the layer that chooses the path.

    Three of a park's nine fields are Tier 1 content (ADR-0244 §2), so where the file is
    and who can read it are this root's obligations rather than the store's: the store
    takes a path with no default, and this is the layer that supplies one under
    ``Settings.data_dir``.
    """
    engine = build_engine(_settings(configured=False), data_dir=tmp_path)
    await engine.aclose()

    assert stat.S_IMODE((tmp_path / "parked_reads.db").stat().st_mode) == 0o600


async def test_the_store_is_closed_by_the_engines_ordered_shutdown(tmp_path: Path) -> None:
    """ADR-0042 §2, asserted on the object rather than only through the census.

    ``tests/app/test_composition_shutdown_roster.py`` holds this for *every* store the
    build opens and would catch a missing closer on the day it was added. This case says
    the same thing where a reader of this decision would look for it, and says what is
    left behind without it: a `-wal` beside a Tier 1 database holding a standing
    question's composed query, objective and plan.
    """
    engine = build_engine(_settings(configured=False), data_dir=tmp_path)
    operations = engine._parked_reads
    assert operations is not None
    store = operations._store
    assert isinstance(store, SqliteParkedReads)

    await engine.aclose()

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        store._conn.execute("SELECT 1")
