"""``SqliteDeferralStore`` passes the shared conformance suite, plus its own parts.

ADR-0028 §8's convention applied to a third store: the suite is bound to the
**production** store as well as to the canonical fake, because a suite bound only
to the double certifies the double while the real store drifts.

Beside the binding are the properties that belong to *this* backend and to no
contract: the owner-only file mode ADR-0004 §4 requires of a Tier 1 store, the
durability of a question across a reopen, and the refusals a corrupt row earns.
"""

from __future__ import annotations

import contextlib
import sqlite3
import stat
import threading
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from deferral_store_contract import (
    DeferralStoreContract,
    DeferralStoreFactory,
    DeferralStoreRebuild,
    ScriptedTokens,
    _admit,
    _proposal,
)

from ai_assistant.core.errors import DeferralStoreError
from ai_assistant.memory.deferral_store import (
    SqliteDeferralStore,
    _run_to_completion,
    _secret_claim_id,
)
from ai_assistant.testing.cancellation import (
    ResourceLog,
    SuspendedMidWrite,
    ThreadSuspension,
    worker_finished_before_the_first_check,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator
    from pathlib import Path

    from ai_assistant.core.protocols import DeferralStore

_TTL = timedelta(days=7)
_LIMIT = 200


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


class TestSqliteDeferralStoreContract(DeferralStoreContract):
    """Runs SqliteDeferralStore through the shared DeferralStore conformance suite."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> Iterator[DeferralStore]:
        realised = SqliteDeferralStore(path=tmp_path / "deferrals.db", now=_fixed_now)
        try:
            yield realised
        finally:
            realised.close()

    @pytest.fixture
    def factory(self, tmp_path: Path) -> Iterator[DeferralStoreFactory]:
        """Build subjects on their own files, closing each when the case ends.

        A file per subject rather than one shared file: several clauses build two
        stores in one case (a cap of one beside a roomy one, an "ask me forever" one),
        and sharing a path would make them one queue.
        """
        opened: list[SqliteDeferralStore] = []

        def build(
            *,
            now: Callable[[], datetime],
            retention: timedelta | None,
            queue_limit: int,
            new_claim_id: Callable[[], str],
        ) -> DeferralStore:
            realised = SqliteDeferralStore(
                path=tmp_path / f"deferrals-{len(opened)}.db",
                now=now,
                retention=retention,
                queue_limit=queue_limit,
                new_claim_id=new_claim_id,
            )
            opened.append(realised)
            return realised

        try:
            yield build
        finally:
            for realised in opened:
                realised.close()

    @pytest.fixture
    def rebuild(self) -> DeferralStoreRebuild:
        """Reopen the same database file under different tuning.

        What ADR-0078 §2's stored-retention clause needs: a conforming store reads
        its lifetime once at construction, so "the setting has changed since this
        question was admitted" is only expressible across two instances over one
        file. The path is read off the subject deliberately — it is the one fact
        about *which* durable state to reopen, and no contract method exposes it.
        """
        reopened: list[SqliteDeferralStore] = []

        def build(
            store: DeferralStore,
            *,
            now: Callable[[], datetime],
            retention: timedelta | None,
            queue_limit: int,
        ) -> DeferralStore:
            assert isinstance(store, SqliteDeferralStore)
            # The path is the one fact about *which* durable state to reopen, and
            # no contract read names it.
            path = store._path
            store.close()
            realised = SqliteDeferralStore(
                path=path, now=now, retention=retention, queue_limit=queue_limit
            )
            reopened.append(realised)
            return realised

        return build

    @contextlib.asynccontextmanager
    async def store_suspended_mid_write(
        self,
        *,
        now: Callable[[], datetime],
        retention: timedelta | None = _TTL,
        queue_limit: int = _LIMIT,
        new_claim_id: Callable[[], str] | None = None,
    ) -> AsyncIterator[SuspendedMidWrite[DeferralStore]]:
        """Park a named write's worker thread inside the connection's turn.

        ``arm(operation)`` wraps that operation's ``_<operation>_sync`` — inside
        ``async with self._lock`` and inside the thread the event loop cannot
        interrupt, which is exactly where a compare-and-set can be handed over early
        — so the first worker to reach it blocks and every later one runs free.
        Blocking there is what makes the case deterministic: left to run, a commit
        finishes in microseconds and whether the second caller arrives while the
        worker still holds the connection would be a race, so the invariant would be
        exercised only sometimes.

        Its own store on its own connection, not the ``store`` fixture's: the
        suspended worker is parked for the length of the case, and sharing would make
        an unrelated failure hang instead of fail.
        """
        realised = SqliteDeferralStore(
            path=":memory:",
            now=now,
            retention=retention,
            queue_limit=queue_limit,
            new_claim_id=new_claim_id or ScriptedTokens([]),
        )
        log = ResourceLog()
        suspension = ThreadSuspension()

        def arm(operation: str) -> ThreadSuspension:
            original = getattr(realised, f"_{operation}_sync")
            armed = threading.Event()

            def blocking(*args: object) -> object:
                with log.inside():  # the span the connection is genuinely in use for
                    if not armed.is_set():  # the first worker only; later ones run free
                        armed.set()
                        suspension.hold()
                    return original(*args)

            setattr(realised, f"_{operation}_sync", blocking)
            return suspension

        try:
            yield SuspendedMidWrite(store=realised, log=log, arm=arm)
        finally:
            suspension.release()
            realised.close()


async def test_the_database_file_is_owner_only(tmp_path: Path) -> None:
    """ADR-0004 §4, and it is not incidental: the queue holds the user's own words.

    Restricted before the first write rather than after the schema is built, because
    SQLite copies the database file's mode onto every rollback journal it creates —
    so a journal written while the file still carried the process umask would be
    world-readable and would hold Tier 1 pages after an interrupted write.
    """
    path = tmp_path / "deferrals.db"
    store = SqliteDeferralStore(path=path, now=_fixed_now)
    try:
        await _admit(store, "d1")
    finally:
        store.close()

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_sidecar_that_was_already_there_is_restricted_at_open(tmp_path: Path) -> None:
    """ADR-0004 §4 reaches a sidecar this process did not create (#490).

    SQLite copies the database file's mode onto a sidecar **it creates**, which is
    what makes restricting the file before the first statement enough for those. It
    does nothing for one already on disk: a ``-wal``/``-shm`` left by a process that
    put this file into WAL mode keeps its own mode across a reopen and then takes
    Tier 1 pages.

    Planted at ``0644`` and asserted after a *reopen*, because that is the only shape
    that can fail: a sidecar SQLite makes for an already-``0600`` file is ``0600``
    however this store is written. Nothing in this codebase sets ``journal_mode``, so
    SQLite neither reads nor writes these two — the mode asserted is this store's own
    chmod and nothing else.
    """
    path = tmp_path / "deferrals.db"
    SqliteDeferralStore(path=path, now=_fixed_now).close()
    sidecars = [path.with_name(f"{path.name}{suffix}") for suffix in ("-wal", "-shm")]
    for sidecar in sidecars:
        sidecar.touch()
        sidecar.chmod(0o644)

    SqliteDeferralStore(path=path, now=_fixed_now).close()

    assert [stat.S_IMODE(each.stat().st_mode) for each in sidecars] == [0o600, 0o600]


async def test_a_question_survives_a_reopen(tmp_path: Path) -> None:
    """The whole point of a durable queue: a question outlives the process.

    ADR-0078 §1's argument for a store rather than a field is that the thing it
    persists — a question the system asked and has not been answered — must survive
    the process that asked it, which is what the observer's questions require.
    """
    path = tmp_path / "deferrals.db"
    first = SqliteDeferralStore(path=path, now=_fixed_now, retention=_TTL)
    try:
        admitted = await _admit(first, "d1", _proposal("a durable question", conflicts=("c1",)))
    finally:
        first.close()

    second = SqliteDeferralStore(path=path, now=_fixed_now, retention=_TTL)
    try:
        assert await second.get("d1") == admitted
        assert [row.id for row in await second.pending()] == ["d1"]
    finally:
        second.close()


async def test_a_claim_token_never_reaches_the_file_a_reader_would_export(
    tmp_path: Path,
) -> None:
    """A capability is not the user's data (ADR-0078 §2).

    The token is stored — the compare-and-set needs it — but it is not a field of the
    record, so no read republishes it and a reopened store's ``export`` cannot leak
    it to anything that reads the file.
    """
    path = tmp_path / "deferrals.db"
    store = SqliteDeferralStore(
        path=path, now=_fixed_now, new_claim_id=ScriptedTokens(["a-very-distinctive-token"])
    )
    try:
        await _admit(store, "d1")
        claim = await store.claim("d1")
        assert claim is not None
        exported = [row.model_dump(mode="json") for row in await store.export()]
    finally:
        store.close()

    assert claim.claim_id == "a-very-distinctive-token"
    assert all("a-very-distinctive-token" not in str(row) for row in exported)


def test_an_unopenable_path_is_the_seams_own_error(tmp_path: Path) -> None:
    """Not a raw ``sqlite3.Error``: an adapter's ``AssistantError`` boundary catches
    this seam's error, and nothing else.
    """
    occupied = tmp_path / "occupied"
    occupied.mkdir()

    with pytest.raises(DeferralStoreError):
        SqliteDeferralStore(path=occupied, now=_fixed_now)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        pytest.param("state", "invented", id="a-state-no-code-knows"),
        pytest.param("deferred_at", 1.5, id="a-non-integer-instant"),
        pytest.param("retention", 1.5, id="a-non-integer-duration"),
        pytest.param("proposal", "{not json", id="an-unparseable-proposal"),
        pytest.param("id", None, id="an-unusable-id"),
    ],
)
async def test_a_corrupt_row_is_reported_rather_than_guessed_at(
    tmp_path: Path, column: str, value: object
) -> None:
    """A store fault, reported as one (ADR-0078 §2).

    SQLite's ``INTEGER`` affinity is a preference rather than a constraint, so a
    ``REAL`` stays a ``REAL`` in the column — and coercing one would read back as
    data instead of as the corruption it is. A state no code knows is corruption
    too, not a state to guess at.
    """
    path = tmp_path / "deferrals.db"
    store = SqliteDeferralStore(path=path, now=_fixed_now)
    try:
        await _admit(store, "d1")
    finally:
        store.close()

    with sqlite3.connect(path) as raw:
        raw.execute(f"UPDATE deferrals SET {column} = ?", (value,))  # noqa: S608 — a parametrised id
    raw.close()

    reopened = SqliteDeferralStore(path=path, now=_fixed_now)
    try:
        with pytest.raises(DeferralStoreError):
            await reopened.export()
    finally:
        reopened.close()


def test_the_production_store_defaults_to_the_secrets_backed_token_source(
    tmp_path: Path,
) -> None:
    """The assertion that keeps "unpredictable" from being a word in an ADR (§2).

    Injection exists for determinism in tests, but injection alone would let a
    composition root wire a counter and satisfy every word of "fresh" — so the
    default is the guarantee, and a default nothing asserts is a default nothing
    holds.
    """
    store = SqliteDeferralStore(path=tmp_path / "deferrals.db", now=_fixed_now)
    try:
        assert store._new_claim_id is _secret_claim_id
    finally:
        store.close()


@pytest.mark.parametrize(
    "queue_limit",
    [0, -1, 2**63, 1.5, True],
    ids=["zero", "negative", "over-wide", "a-float", "a-bool"],
)
def test_the_production_store_refuses_a_cap_the_queue_cannot_work_under(
    tmp_path: Path, queue_limit: object
) -> None:
    """Refused at construction, in the ``_check_tuning`` shape ADR-0022 §4a ratified.

    A cap of 0 is at capacity before its first admission, so every question would be
    refused and ADR-0078's whole subject would return, by configuration, while the
    system reported health.
    """
    with pytest.raises(ValueError, match="queue_limit"):
        SqliteDeferralStore(
            path=tmp_path / "deferrals.db",
            now=_fixed_now,
            queue_limit=queue_limit,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "retention",
    [timedelta(0), -timedelta(days=1), "P7D"],
    ids=["zero", "negative", "not-a-duration"],
)
def test_the_production_store_refuses_a_lifetime_the_queue_cannot_work_under(
    tmp_path: Path, retention: object
) -> None:
    with pytest.raises(ValueError, match="retention"):
        SqliteDeferralStore(
            path=tmp_path / "deferrals.db",
            now=_fixed_now,
            retention=retention,  # type: ignore[arg-type]
        )


async def test_a_base_exception_from_the_worker_reaches_the_caller() -> None:
    """ADR-0054's relay carries every failure, not only the ``Exception`` half (#680).

    ``_run_to_completion`` answers out of its relay lists alone whenever the worker
    finished before the wait loop's first check. A failure the relay never captured
    leaves both lists empty, so the caller is answered from an empty ``outcome`` —
    an ``IndexError`` standing in for the cause and not chained to it.

    The lever forces that path every time. Without it, which of the two paths a
    caller gets is a race, and a case that only sometimes reaches the defect is not
    evidence about it. ``KeyboardInterrupt`` stands in for the class; ``SystemExit``
    and a ``CancelledError`` raised by the work itself are the other members.

    Its own copy of the helper, deliberately: ADR-0060 refuses this shape a shared
    home, so each copy is a separate place the relay could be narrow (#680).
    """

    def aborts() -> None:
        raise KeyboardInterrupt

    with worker_finished_before_the_first_check(), pytest.raises(KeyboardInterrupt):
        await _run_to_completion(aborts)
