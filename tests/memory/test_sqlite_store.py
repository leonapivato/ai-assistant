"""Tests for the persistent SQLite-backed MemoryStore.

These touch the filesystem and the native ``sqlite-vec`` extension, so the module
is marked ``integration``. They use the deterministic ``HashingEmbedder`` so
retrieval is reproducible and offline.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import pytest
import sqlite_vec
from memory_store_contract import MemoryStoreContract
from pydantic import ValidationError

from ai_assistant.core.errors import (
    IncompatibleStateError,
    MemoryStoreConflictError,
    MemoryStoreError,
)
from ai_assistant.core.protocols import MemoryStore
from ai_assistant.core.types import (
    MemoryKind,
    MemoryRecord,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    PreferenceMemory,
    Provenance,
    SemanticMemory,
    Validity,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory.sqlite_store import _run_to_completion
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing.cancellation import (
    ResourceLog,
    SuspendedMidWrite,
    ThreadSuspension,
    worker_finished_before_the_first_check,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence

    from ai_assistant.core.protocols import Embedder
    from ai_assistant.core.types import Embedding
    from ai_assistant.testing.cancellation import SuspendedCall

pytestmark = pytest.mark.integration

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_NOW = datetime(2026, 6, 1, tzinfo=UTC)
#: How long ``_GatedEmbedder`` waits for a call to arrive before declaring the
#: scenario broken. Generous — only reached when a case has already hung.
_GATE_SECONDS = 5.0
#: How long the first opener holds the meta-insert window open once it has
#: announced itself. A *bound* on how long the second is given to arrive and
#: collide, not a synchronisation primitive — the ordering comes from the
#: announcement. Under ``sqlite3.connect``'s 5.0 s default busy timeout, so a
#: blocked ``BEGIN IMMEDIATE`` waits it out rather than giving up.
_SETUP_HOLD_SECONDS = 1.0


def _fixed_now() -> datetime:
    return _NOW


def _journal_mode(database: Path) -> int | None:
    """The permission bits of the rollback journal beside ``database``, or ``None``."""
    journal = database.with_name(f"{database.name}-journal")
    return journal.stat().st_mode & 0o777 if journal.exists() else None


def _provenance(
    *, source: MemorySource = MemorySource.OBSERVED, last_updated: datetime = _WHEN
) -> Provenance:
    certain = source is MemorySource.USER_ASSERTED
    return Provenance(source=source, confidence=1.0 if certain else 0.6, last_updated=last_updated)


def _semantic(  # noqa: PLR0913 — one keyword per record axis a case may need to vary
    record_id: str,
    content: str,
    *,
    expires_at: datetime | None = None,
    validity: Validity | None = None,
    source: MemorySource = MemorySource.OBSERVED,
    last_updated: datetime = _WHEN,
) -> MemoryRecord:
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=_provenance(source=source, last_updated=last_updated),
        expires_at=expires_at,
        validity=validity or Validity(),
    )


def _preference(record_id: str, content: str) -> MemoryRecord:
    return PreferenceMemory(
        id=record_id, content=content, preference=content, provenance=_provenance()
    )


class _FlakyEmbedder:
    """A misbehaving embedder for exercising the store's error boundary.

    Returns valid vectors until one of the fault flags is set: ``fail`` yields a
    wrong-sized vector, ``boom`` raises (mimicking a provider outage), and
    ``malformed`` returns a contract-violating result element (``None``).
    """

    def __init__(self) -> None:
        self._inner = HashingEmbedder(dimensions=8)
        self.fail = False
        self.boom = False
        self.malformed = False

    @property
    def model_id(self) -> str:
        return "flaky-8"

    @property
    def dimensions(self) -> int:
        return 8

    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        if self.boom:
            msg = "provider outage"
            raise RuntimeError(msg)
        if self.malformed:
            return cast("list[Embedding]", [None for _ in texts])  # non-sized element
        if self.fail:
            return [[0.0, 0.0, 0.0] for _ in texts]  # wrong length (3 != 8)
        return await self._inner.embed(texts)


@pytest.fixture
def make_store(tmp_path: Path) -> Iterator[Callable[..., SqliteMemoryStore]]:
    """Build stores that are closed on teardown so temp files release cleanly."""
    created: list[SqliteMemoryStore] = []

    def _make(
        *,
        embedder: Embedder | None = None,
        dimensions: int = 256,
        now: Callable[[], datetime] = _fixed_now,
    ) -> SqliteMemoryStore:
        store = SqliteMemoryStore(
            path=tmp_path / "memory.db",
            embedder=embedder if embedder is not None else HashingEmbedder(dimensions=dimensions),
            now=now,
        )
        created.append(store)
        return store

    yield _make
    for store in created:
        store.close()


def test_store_conforms_to_protocol(make_store: Callable[..., SqliteMemoryStore]) -> None:
    assert isinstance(make_store(), MemoryStore)


async def test_add_and_get_round_trips_typed_record(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()

    await store.add(_preference("p1", "prefers concise replies"))
    got = await store.get("p1")

    assert isinstance(got, PreferenceMemory)
    assert got.id == "p1"
    assert got.preference == "prefers concise replies"


async def test_get_missing_returns_none(make_store: Callable[..., SqliteMemoryStore]) -> None:
    store = make_store()
    assert await store.get("nope") is None


async def test_search_ranks_by_similarity_and_scores(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("c1", "coffee tea"))
    await store.add(_semantic("c2", "coffee milk"))
    await store.add(_semantic("r1", "rocket ship"))

    results = await store.search("coffee")

    assert {results[0].id, results[1].id} == {"c1", "c2"}
    assert results[-1].id == "r1"
    assert results[0].score is not None
    assert results[0].score > results[-1].score  # type: ignore[operator]


async def test_add_overwrites_same_id(make_store: Callable[..., SqliteMemoryStore]) -> None:
    store = make_store()

    await store.add(_semantic("1", "old note about tea"))
    await store.add(_semantic("1", "new note about coffee"))

    got = await store.get("1")
    assert got is not None
    assert got.content == "new note about coffee"


async def test_search_filters_by_kind(make_store: Callable[..., SqliteMemoryStore]) -> None:
    store = make_store()
    await store.add(_semantic("s", "coffee fact"))
    await store.add(_preference("p", "coffee preference"))

    results = await store.search("coffee", kinds=[MemoryKind.PREFERENCE])

    assert [r.id for r in results] == ["p"]


async def test_empty_query_matches_nothing(make_store: Callable[..., SqliteMemoryStore]) -> None:
    store = make_store()
    await store.add(_semantic("1", "some content"))
    assert await store.search("   ") == []


async def test_non_positive_limit_matches_nothing(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("1", "coffee"))

    assert await store.search("coffee", limit=0) == []
    assert await store.search("coffee", limit=-3) == []


@pytest.mark.parametrize(
    "limit",
    [
        # Just over the real ceiling: limit * _RESULT_OVERFETCH (8) = 8000 > 4096,
        # the sqlite-vec KNN ``k`` cap. A plausible misconfiguration, not absurd.
        1_000,
        # The value the issue theorised the crash against (signed 64-bit bind
        # range); the same clamp covers it.
        1_152_921_504_606_846_975,
    ],
)
async def test_over_large_limit_serves_instead_of_overflowing_knn(
    make_store: Callable[..., SqliteMemoryStore],
    limit: int,
) -> None:
    # Unclamped, ``limit * _RESULT_OVERFETCH`` exceeds sqlite-vec's KNN ``k`` cap
    # of 4096 and the query raises an opaque ``sqlite3.OperationalError`` on the
    # binding rather than returning (issue #115). The clamp turns it into a clean
    # result — no allocation the size of the limit, and no crash.
    store = make_store()
    await store.add(_semantic("c1", "coffee tea"))
    await store.add(_semantic("c2", "coffee milk"))

    results = await store.search("coffee", limit=limit)

    assert {record.id for record in results} == {"c1", "c2"}


async def test_failed_write_leaves_store_unchanged(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    embedder = _FlakyEmbedder()
    store = make_store(embedder=embedder)
    await store.add(_semantic("1", "original content"))

    embedder.fail = True
    with pytest.raises(MemoryStoreError):
        await store.add(_semantic("1", "corrupt overwrite"))

    embedder.fail = False
    got = await store.get("1")
    assert got is not None
    assert got.content == "original content"  # the failed overwrite did not apply
    assert [r.id for r in await store.search("original")] == ["1"]  # still consistent


async def test_rollback_on_mid_transaction_failure(
    make_store: Callable[..., SqliteMemoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store()
    await store.add(_semantic("1", "original content"))

    # A malformed serialized vector makes the vec_records INSERT fail *after* the
    # record UPDATE/DELETE in an overwrite, so this exercises the rollback path
    # itself (not the up-front length guard).
    monkeypatch.setattr(
        "ai_assistant.memory.sqlite_store.sqlite_vec.serialize_float32",
        lambda _vector: b"\x00",
    )
    with pytest.raises(MemoryStoreError):
        await store.add(_semantic("1", "overwrite that fails mid-write"))

    monkeypatch.undo()
    got = await store.get("1")
    assert got is not None
    assert got.content == "original content"  # UPDATE/DELETE were rolled back


async def test_write_atomic_rolls_back_a_mid_batch_backend_failure(
    make_store: Callable[..., SqliteMemoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fault-injection the shared suite cannot drive (ADR-0046 §Consequences): make
    # the *second* element's vector write fail mid-transaction and assert the first
    # element's row AND its vector row did not persist — proving a real rollback,
    # not per-element commits — and that the raised error is MemoryStoreError with
    # the sqlite3 exception retained as its cause, never a leaked provider error
    # (ADR-0028 §5). Without this an accidental per-element commit passes every
    # logical case while violating §4's all-or-nothing.
    store = make_store()
    real = sqlite_vec.serialize_float32
    calls = {"n": 0}

    def flaky(vector: object) -> bytes:
        calls["n"] += 1
        if calls["n"] >= 2:  # the second element's vector: a malformed blob
            return b"\x00"  # a bad float32 blob makes the vec_records INSERT raise
        return cast("bytes", real(vector))

    monkeypatch.setattr("ai_assistant.memory.sqlite_store.sqlite_vec.serialize_float32", flaky)
    with pytest.raises(MemoryStoreError) as exc_info:
        await store.write_atomic(
            [
                MemoryWrite(record=_semantic("a", "first element")),
                MemoryWrite(record=_semantic("b", "second element")),
            ]
        )
    monkeypatch.undo()

    assert not isinstance(exc_info.value, MemoryStoreConflictError)  # a fault, not a conflict
    assert isinstance(exc_info.value.__cause__, sqlite3.Error)  # sqlite3 cause retained
    assert await store.get("a") is None  # the first element rolled back...
    assert await store.get("b") is None
    # ...its record row and its vector row both, not just the payload.
    assert store._conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0
    assert store._conn.execute("SELECT COUNT(*) FROM vec_records").fetchone()[0] == 0


async def test_write_atomic_rolls_back_a_non_sqlite_mid_batch_error(
    make_store: Callable[..., SqliteMemoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A mid-transaction failure that is *not* a sqlite3.Error — serializing a
    # malformed vector raises ValueError after the first element is already
    # written — must still roll the whole batch back and surface as
    # MemoryStoreError, never escape with the transaction left open (which would
    # leave the first element a committable partial batch, breaking §4).
    store = make_store()
    real = sqlite_vec.serialize_float32
    calls = {"n": 0}

    def raises_on_second(vector: object) -> bytes:
        calls["n"] += 1
        if calls["n"] >= 2:
            msg = "not a float32 vector"
            raise ValueError(msg)
        return cast("bytes", real(vector))

    monkeypatch.setattr(
        "ai_assistant.memory.sqlite_store.sqlite_vec.serialize_float32", raises_on_second
    )
    with pytest.raises(MemoryStoreError) as exc_info:
        await store.write_atomic(
            [
                MemoryWrite(record=_semantic("a", "first element")),
                MemoryWrite(record=_semantic("b", "second element")),
            ]
        )
    monkeypatch.undo()

    assert isinstance(exc_info.value.__cause__, ValueError)  # the raw fault retained, wrapped
    assert await store.get("a") is None  # first element rolled back, not committable
    assert store._conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0
    # The transaction was closed by the rollback, so the store is still usable —
    # proof no half-open transaction lingers to commit the partial batch later.
    await store.add(_semantic("c", "still works"))
    assert await store.get("c") is not None


async def test_a_frozen_record_cannot_be_mutated_in_the_construct_then_await_window(
    tmp_path: Path,
) -> None:
    # ADR-0056 pinned add()'s snapshot boundary at the coroutine's first line so a
    # mutation made after the coroutine was built but before it was awaited would
    # be captured consistently. ADR-0068 freezes the record, so that mutation is
    # now unrepresentable and the boundary question is moot: the write can only
    # ever reflect the record as it was constructed.
    #
    # The mid-embed aliasing tears that ADR-0056/#286 and ADR-0046 §3 guarded
    # against — an embedder rewriting a submitted record's id or content while the
    # write is suspended — are likewise unrepresentable now, and the generic
    # defence is verified for this backend by
    # ``TestSqliteMemoryStoreContract.test_add_cannot_tear_on_a_mid_flight_mutation_of_its_record``.
    store = SqliteMemoryStore(path=tmp_path / "boundary.db", embedder=HashingEmbedder(dimensions=8))
    try:
        rec = _semantic("orig", "alpha")
        pending = store.add(rec)  # coroutine built; body (and the snapshot) not run yet
        with pytest.raises(ValidationError):
            rec.content = "mutated coffee"  # frozen: the window carries no mutation
        returned = await pending

        assert returned == "orig"
        got = await store.get("orig")
        assert got is not None
        assert got.content == "alpha"  # the constructed record, unchanged
        assert [r.id for r in await store.search("alpha")] == ["orig"]
    finally:
        store.close()


async def test_expiry_precision_survives_at_the_datetime_range_extreme(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    # issue #289: near year 9999 a REAL POSIX-seconds column cannot resolve
    # microseconds — its ulp is tens of µs — so an expires_at one µs after now
    # would collapse onto now and the ``expires_at > now`` pre-filter would hide a
    # record that is still live. With an integer µs epoch the comparison is exact.
    expires = datetime(9999, 1, 1, tzinfo=UTC)
    just_before = datetime(9998, 12, 31, 23, 59, 59, 999_999, tzinfo=UTC)  # 1 µs earlier
    assert expires.timestamp() == just_before.timestamp()  # the float collision, proven
    store = make_store(now=lambda: just_before)
    await store.add(_semantic("edge", "coffee at the range extreme", expires_at=expires))

    assert await store.get("edge") is not None  # not expired: expires_at > now, exactly
    assert [r.id for r in await store.search("coffee")] == ["edge"]  # search agrees


async def test_valid_until_precision_survives_at_the_datetime_range_extreme(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    # issue #289, the validity axis: search has no exact backstop for valid_until,
    # so a float collision at the range extreme would wrongly retire a live record.
    # A valid_until one µs after now must keep the record live in get AND search.
    valid_until = datetime(9999, 1, 1, tzinfo=UTC)
    just_before = datetime(9998, 12, 31, 23, 59, 59, 999_999, tzinfo=UTC)  # 1 µs earlier
    assert valid_until.timestamp() == just_before.timestamp()  # the float collision
    store = make_store(now=lambda: just_before)
    await store.add(
        _semantic("edge", "coffee still valid", validity=Validity(valid_until=valid_until))
    )

    assert await store.get("edge") is not None  # window still open: now < valid_until
    assert [r.id for r in await store.search("coffee")] == ["edge"]


async def test_write_atomic_recovers_to_neither_write_after_a_crash(tmp_path: Path) -> None:
    # ADR-0046 §4's durability obligation, which the in-process fault test above
    # cannot reach: a process killed mid-batch (after the first transactional write,
    # before COMMIT) must recover, on reopen, to *neither* write committed — never
    # the window-close alone, the ADR-0045 §8 regression this primitive prevents.
    db = tmp_path / "crash.db"
    child = Path(__file__).parent / "_atomic_crash_child.py"

    # Run the child off the event loop: subprocess.run blocks, and the crash test
    # only needs the child to have finished before it reopens the database.
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, str(child), str(db)],
        capture_output=True,
        text=True,
        check=False,
    )

    # 42 is the child's mid-batch injection point; 99 would mean the batch ran to
    # completion (no crash), 0/other a clean exit — either would void the test.
    assert result.returncode == 42, f"child did not crash mid-batch: {result.stderr}"

    reopened = SqliteMemoryStore(path=db, embedder=HashingEmbedder(dimensions=8))
    try:
        target = await reopened.get("T")
        assert target is not None  # T not left window-closed: the UPSERT rolled back
        assert target.validity.valid_until is None  # still the open, pre-batch record
        assert await reopened.get("P") is None  # the correction never landed
    finally:
        reopened.close()


def _orphan_vector_rowids(database: Path) -> list[int]:
    """Vector rows whose ``rowid`` names no record — the #526 corruption, directly.

    ``records`` and ``vec_records`` are joined by ``rowid`` with **no foreign
    key**: ``vec_records`` is a ``vec0`` virtual table, so SQLite cannot enforce
    one, and nothing but the store's own transaction discipline keeps the two
    tables agreeing. That is why this is asserted against the raw file rather than
    through the store's API — ``search`` inner-joins the two, so an orphan makes a
    result quietly *missing* rather than wrong, and every public read would report
    a corrupt database as a healthy empty one.
    """
    raw = sqlite3.connect(database)
    try:
        raw.enable_load_extension(True)
        sqlite_vec.load(raw)
        raw.enable_load_extension(False)
        return [
            row[0]
            for row in raw.execute(
                "SELECT v.rowid FROM vec_records v "
                "LEFT JOIN records r ON r.rowid = v.rowid WHERE r.rowid IS NULL"
            )
        ]
    finally:
        raw.close()


@pytest.mark.skipif(sys.platform == "win32", reason="the child's hold assumes POSIX scheduling")
async def test_a_persist_holds_off_a_deletion_in_another_process(tmp_path: Path) -> None:
    """#526's exclusion, across the boundary the claim is actually about.

    Every other concurrency case in this module is one process, and each passes on
    the store's own ``asyncio.Lock`` alone — so none of them can tell
    ``BEGIN IMMEDIATE`` from the deferred transaction the driver would otherwise
    open. Only two engines really running at once can, which is the same reason
    ``SqliteConversationStore``'s suite drives its exclusion across processes.

    This is deliberately the condition **ADR-0083 §12 says makes the asymmetry
    urgent again** — exclusivity relaxed, two writers over one ``memory.db``. Under
    the hub there is one writing process and this cannot arise; the case exists so
    that the day exclusivity is relaxed, the discipline is already in place and
    provably so, rather than re-derived from the asymmetry.

    The child pauses between ``_persist_record``'s rowid read and its first write
    and announces itself from inside, so the collision is *attempted* on every run
    rather than whenever the scheduler arranges it. With the write lock taken up
    front the deletion below waits, the overwrite lands whole, and the deletion
    then removes both rows. Without it the deletion lands mid-sequence and the
    child's ``INSERT INTO vec_records`` writes a vector against a ``rowid`` that no
    longer names a record — an orphan ``search``'s KNN matches and then fails to
    join, which is worse than a lost write because no public read reports it.
    """
    db = tmp_path / "memory.db"
    child = Path(__file__).parent / "_begin_immediate_child.py"
    store = SqliteMemoryStore(path=db, embedder=HashingEmbedder(dimensions=8))
    try:
        await store.add(_semantic("T", "coffee target"))

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(child),
            str(db),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdout is not None
        # The rendezvous. Generous, because it is only reached when the child has
        # already failed to start — not a bound on the interleaving itself.
        announcement = await asyncio.wait_for(process.stdout.readline(), timeout=_GATE_SECONDS * 6)
        assert announcement.strip() == b"inside", "the child never reached the window"

        # The competing writer, inside the window the announcement opened.
        deleted = await store.delete("T")
    finally:
        store.close()

    _, stderr = await process.communicate()
    # 43 is "the hold never fired": the child's write took a path it does not
    # recognise, so the deletion above raced nothing and a pass would be vacuous.
    assert process.returncode == 0, f"child did not complete its overwrite: {stderr.decode()}"
    assert deleted is True

    assert _orphan_vector_rowids(db) == [], (
        "a deletion interleaved with an overwrite left a vector row naming no "
        "record, so the read-then-write is not atomic across processes"
    )

    reopened = SqliteMemoryStore(path=db, embedder=HashingEmbedder(dimensions=8))
    try:
        # Whichever order the two landed in, the file is internally consistent:
        # the deletion is last, so nothing is left behind either.
        assert await reopened.get("T") is None
        assert await reopened.search("coffee") == []
    finally:
        reopened.close()


#: How long the parent holds a ``get_many`` chunk boundary open once the child has
#: been signalled — a *bound* on how long the competing write is given to land, not
#: a synchronisation primitive. Comfortably more than an unblocked ``add`` needs and
#: comfortably under ``sqlite3.connect``'s 5.0 s default busy timeout, so the child
#: waits the parent's read transaction out rather than giving up.
_INTERLEAVE_HOLD_SECONDS = 1.0
#: ``SQLITE_LIMIT_VARIABLE_NUMBER`` narrowed to leave room for exactly one id
#: beside ``get_many``'s two ``now`` parameters, so a two-id call really is two
#: statements and there is a chunk boundary to interleave at. The production limit
#: is 32,766, which no test could reach by volume — and narrowing the *real* knob
#: exercises the real chunking path rather than a stubbed one.
_ONE_ID_PER_STATEMENT = 3


@pytest.mark.skipif(sys.platform == "win32", reason="the child's hold assumes POSIX scheduling")
async def test_get_many_is_one_snapshot_across_its_chunks(tmp_path: Path) -> None:
    """The chunked batch read is one snapshot of the *store*, not only of the clock.

    ``get_many`` carries no size cap (ADR-0086 §6), so an ``IN`` clause has to be
    chunked to SQLite's bound-parameter limit. The ``asyncio.Lock`` does not make
    that safe: it serialises coroutines on **this store instance** and does nothing
    about the file. Chunked without a read transaction, this call reads ``a`` in
    chunk 1, another process revises ``b``, chunk 2 reads ``b``, and the result
    pairs values that never coexisted — §6's snapshot violated by the very
    mechanism introduced to keep its promise never to refuse on size.

    Only this store has chunks to interleave between, which is why the case lives
    here and not in the shared suite (ADR-0086 §8): the shared suite asserts the
    observable snapshot and stops, because a conforming store may answer in one
    request, one statement or one in-memory snapshot and has no portable boundary
    to inject at.

    Deliberately the condition **ADR-0083 §12 says makes the asymmetry urgent
    again** — exclusivity relaxed, two processes over one ``memory.db`` — driven
    the way this module's other cross-process case is: the child announces itself,
    the parent releases it from inside the window, so the collision is *attempted*
    on every run.
    """
    db = tmp_path / "memory.db"
    child_path = Path(__file__).parent / "_get_many_snapshot_child.py"
    store = SqliteMemoryStore(path=db, embedder=HashingEmbedder(dimensions=8))
    # A blocking ``Popen`` rather than an asyncio subprocess: the go-signal is sent
    # from the worker thread ``_run_to_completion`` dispatched to, and an
    # ``asyncio.StreamWriter`` is not safe to touch from off the loop. A real OS
    # pipe is, so the reads that *do* happen on the loop go through ``to_thread``.
    process = await asyncio.to_thread(
        subprocess.Popen,  # spawned off the loop, like this module's other child
        [sys.executable, str(child_path), str(db)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stdin is not None
    stdin = process.stdin
    stdout = process.stdout
    try:
        await store.add(_semantic("a", "a as the parent seeded it"))
        await store.add(_semantic("b", "b as the parent seeded it"))
        # The child opens its store *before* the window, so what contends inside it
        # is the write under test and not the child's own `_setup`.
        announcement = await asyncio.wait_for(
            asyncio.to_thread(stdout.readline), timeout=_GATE_SECONDS * 6
        )
        assert announcement.strip() == b"ready", "the child never opened its store"

        store._conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, _ONE_ID_PER_STATEMENT)
        seen = 0

        def release_the_writer_between_chunks(statement: str) -> None:
            # Fires as each statement *starts*, so acting on the second SELECT puts
            # the competing write after chunk 1 has already read `a` and before
            # chunk 2 reads `b` — the boundary, and nowhere else.
            nonlocal seen
            if not statement.lstrip().upper().startswith("SELECT DATA FROM RECORDS"):
                return
            seen += 1
            if seen != 2:
                return
            stdin.write(b"go\n")
            stdin.flush()
            # This runs on the worker thread `_run_to_completion` dispatched to, so
            # blocking it holds the chunk boundary open without stalling the loop.
            time.sleep(_INTERLEAVE_HOLD_SECONDS)

        store._conn.set_trace_callback(release_the_writer_between_chunks)
        try:
            batch = await store.get_many(["a", "b"])
        finally:
            store._conn.set_trace_callback(None)
    finally:
        store.close()

    _, stderr = await asyncio.to_thread(process.communicate)
    assert process.returncode == 0, f"the child's write failed: {stderr.decode()}"
    assert seen >= 2, "the read was not chunked, so nothing was interleaved and this proves nothing"
    assert batch["a"].content == "a as the parent seeded it"
    assert batch["b"].content == "b as the parent seeded it", (
        "the batch returned an old 'a' beside a revision of 'b' that landed after "
        "it — two values that never coexisted, so the chunks were not one snapshot"
    )


async def test_embedder_exception_is_wrapped_as_store_error(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    embedder = _FlakyEmbedder()
    store = make_store(embedder=embedder)

    embedder.boom = True
    with pytest.raises(MemoryStoreError, match="embedder failed"):
        await store.add(_semantic("1", "content"))
    with pytest.raises(MemoryStoreError, match="embedder failed"):
        await store.search("content")

    embedder.boom = False
    embedder.malformed = True  # a non-sized result element must not leak a TypeError
    with pytest.raises(MemoryStoreError, match="embedder failed"):
        await store.add(_semantic("1", "content"))


async def test_wrong_sized_query_vector_raises_store_error(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    embedder = _FlakyEmbedder()
    store = make_store(embedder=embedder)
    await store.add(_semantic("1", "content"))

    embedder.fail = True  # search now embeds the query to a wrong-sized vector
    with pytest.raises(MemoryStoreError, match="expected 8"):
        await store.search("content")


async def test_connect_failure_is_wrapped(tmp_path: Path) -> None:
    # A path under a non-existent directory makes sqlite3.connect() itself raise,
    # before any connection exists to close.
    missing = tmp_path / "no_such_dir" / "memory.db"
    with pytest.raises(MemoryStoreError, match="failed to open memory store"):
        SqliteMemoryStore(path=missing, embedder=HashingEmbedder(dimensions=8))


async def test_setup_failure_is_wrapped_and_closes_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Force a failure *after* the connection is opened; the store must translate
    # it to MemoryStoreError and close the half-open connection (no leak).
    captured: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    # Every argument is required and forwarded, mirroring the store's own call
    # exactly: the store connects in autocommit mode so that its `BEGIN
    # IMMEDIATE`/`COMMIT` are its own, and a double that defaulted the argument
    # away would leave this case exercising a differently-configured connection
    # from the one the store actually opens — and would go on silently doing so if
    # the store ever stopped passing it.
    def _capturing_connect(
        database: str,
        *,
        check_same_thread: bool,
        isolation_level: Literal["DEFERRED", "EXCLUSIVE", "IMMEDIATE"] | None,
    ) -> sqlite3.Connection:
        conn = real_connect(
            database, check_same_thread=check_same_thread, isolation_level=isolation_level
        )
        captured.append(conn)
        return conn

    def _boom(_conn: object) -> None:
        raise sqlite3.OperationalError("cannot load extension")

    monkeypatch.setattr("ai_assistant.memory.sqlite_store.sqlite3.connect", _capturing_connect)
    monkeypatch.setattr("ai_assistant.memory.sqlite_store.sqlite_vec.load", _boom)

    with pytest.raises(MemoryStoreError, match="failed to open memory store"):
        SqliteMemoryStore(path=tmp_path / "memory.db", embedder=HashingEmbedder(dimensions=8))

    assert len(captured) == 1  # a connection was opened
    with pytest.raises(sqlite3.ProgrammingError):
        captured[0].execute("SELECT 1")  # ...and closed on the failure path


def _connect_holding_the_first_meta_insert(
    real_connect: Callable[..., sqlite3.Connection], inside: threading.Event
) -> Callable[..., sqlite3.Connection]:
    """A ``sqlite3.connect`` whose *first* connection stops inside setup's window.

    The rendezvous the setup race needs: the hold is placed between
    ``_verify_or_init_meta``'s read and its insert, and ``inside`` is set from in
    there, so a second opener can be released at the one moment its own read would
    observe the same empty ``meta``. Later connections are returned unhooked, so
    the store the second thread opens behaves exactly as it does in production.
    """
    connections = 0
    guard = threading.Lock()

    def _connect(database: str, **kwargs: object) -> sqlite3.Connection:
        nonlocal connections
        conn = real_connect(database, **kwargs)
        with guard:
            connections += 1
            if connections != 1:
                return conn
        fired = False

        # Fires as each statement starts, so keying it on the meta insert places
        # the hold after the read above has already returned empty.
        def hold(statement: str) -> None:
            nonlocal fired
            if fired or not statement.lstrip().upper().startswith("INSERT INTO META"):
                return
            fired = True
            inside.set()
            time.sleep(_SETUP_HOLD_SECONDS)

        conn.set_trace_callback(hold)
        return conn

    return _connect


def test_a_second_open_of_a_fresh_file_waits_for_the_first_to_initialise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setup's own read-then-write is under the write lock too (#526).

    ``_verify_or_init_meta`` reads ``meta`` and inserts the embedding model and
    dimension only if it found nothing, so setup has exactly the shape the
    mutations do — and ``SqlitePlanStore._setup`` and ``SqliteAuditTrail._setup``
    both take ``BEGIN IMMEDIATE`` for it. This is the case that says so here.

    **Staged rather than merely simultaneous**, which is what gives it teeth.
    ``SqlitePlanStore``'s equivalent releases two threads from a barrier, and a
    barrier only makes them *runnable*: the window between the meta read and the
    meta insert is a few microseconds wide, so both openers usually miss it and
    the case passes on a deferred setup as happily as on an immediate one —
    verified, by reverting. Here the first opener is stopped *inside* the window
    and the second is released only once it is in there, so the collision is
    attempted on every run.

    With the write lock taken at the top of setup the second opener's ``BEGIN
    IMMEDIATE`` waits, then finds ``meta`` already populated and skips the insert;
    both constructors succeed. Without it the second opener reads an empty ``meta``
    and inserts, and the first's insert then loses a primary-key race on
    ``meta.key`` — which surfaces as a store that will not open at all.
    """
    path = tmp_path / "memory.db"
    real_connect = sqlite3.connect
    inside = threading.Event()
    guard = threading.Lock()
    monkeypatch.setattr(
        "ai_assistant.memory.sqlite_store.sqlite3.connect",
        _connect_holding_the_first_meta_insert(real_connect, inside),
    )

    opened: list[SqliteMemoryStore] = []
    errors: list[BaseException] = []

    def _open(*, wait: bool) -> None:
        if wait and not inside.wait(timeout=_GATE_SECONDS):
            errors.append(AssertionError("the first opener never reached the meta insert"))
            return
        try:
            store = SqliteMemoryStore(path=path, embedder=HashingEmbedder(dimensions=8))
        except BaseException as exc:
            with guard:
                errors.append(exc)
        else:
            with guard:
                opened.append(store)

    threads = [
        threading.Thread(target=_open, kwargs={"wait": False}),
        threading.Thread(target=_open, kwargs={"wait": True}),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert not errors, f"a concurrent first open failed: {errors}"
        assert len(opened) == 2
    finally:
        for store in opened:
            store.close()

    # `real_connect`, not `sqlite3.connect`: the patch above is on the shared
    # `sqlite3` module object, so it is still in force here.
    raw = real_connect(path)
    try:
        recorded = dict(raw.execute("SELECT key, value FROM meta").fetchall())
    finally:
        raw.close()
    # One row per key: the loser skipped the insert rather than duplicating or
    # half-writing the identity a later open judges its embedder against.
    assert recorded == {
        "embedding_model": HashingEmbedder(dimensions=8).model_id,
        "dimensions": "8",
    }


def _assert_opens_with_the_write_lock(statements: list[str], *, what: str) -> None:
    """Assert one write path took the write lock **before its first read**.

    The staged races elsewhere in this module prove the lock, once held, really
    does exclude a second process. They cannot prove *when* it was taken: each
    releases its competitor at the first write, so an implementation that left the
    read outside the transaction and issued ``BEGIN IMMEDIATE`` immediately before
    the write would satisfy them and still leave the read-to-``BEGIN`` window
    open — which is the entire window #526 is about. This is the deterministic
    other half, asserted on the statement stream rather than on a race.

    Also pins the two ends the store depends on structurally: exactly one
    transaction (a second ``BEGIN`` on the shared connection raises), and a
    ``COMMIT`` last, so a path that returns early cannot abandon an open
    transaction that would poison the next caller's ``BEGIN``.
    """
    assert statements, f"{what} ran no SQL at all"
    opened = statements[0].strip()
    assert opened.upper() == "BEGIN IMMEDIATE", (
        f"{what} began with {opened!r}. The write lock has to be the *first* "
        f"statement: a `BEGIN IMMEDIATE` issued any later leaves every read before "
        f"it outside the transaction, which is exactly the exposure #526 names."
    )
    begins = [one for one in statements if one.strip().upper().startswith("BEGIN")]
    assert len(begins) == 1, f"{what} opened {len(begins)} transactions: {begins}"
    assert statements[-1].strip().upper() == "COMMIT", (
        f"{what} ended with {statements[-1]!r} rather than COMMIT, so it left a "
        f"transaction open on the shared connection"
    )


def test_setup_takes_the_write_lock_before_it_inspects_the_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setup's reads — the shape check and the meta read — are inside its transaction.

    ``_migrate_records``' ``PRAGMA table_info`` decides whether to rebuild
    ``records``, and ``_verify_or_init_meta``'s ``SELECT`` decides whether to write
    the store's embedder identity. Both are reads that a write depends on, so both
    have to be under the lock; #526 names the first of them explicitly.
    """
    statements: list[str] = []
    real_connect: Callable[..., sqlite3.Connection] = sqlite3.connect

    def _connect(database: str, **kwargs: object) -> sqlite3.Connection:
        conn = real_connect(database, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr("ai_assistant.memory.sqlite_store.sqlite3.connect", _connect)
    store = SqliteMemoryStore(path=tmp_path / "memory.db", embedder=HashingEmbedder(dimensions=8))
    store.close()

    _assert_opens_with_the_write_lock(statements, what="setup")
    # Named rather than left implicit, so a later change that moved either read
    # out of setup's transaction fails here instead of passing quietly.
    assert "PRAGMA table_info(records)" in statements
    assert "SELECT key, value FROM meta" in statements


async def test_every_mutation_takes_the_write_lock_before_its_first_read(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    """The same assertion, over every write path the store has.

    Each of these reads before it writes — a rowid lookup, a presence check, a
    count, an expiry scan — and each read is the one #526 says must not be
    interleavable. The two that can return early (``delete`` on an absent id,
    ``purge_expired`` with nothing to purge) are driven down that arm too, since
    an early return is where an open transaction would be abandoned.
    """
    store = make_store()
    await store.add(_semantic("seed", "coffee target"))

    async def _recorded(what: str, run: Callable[[], Awaitable[object]]) -> None:
        statements: list[str] = []
        store._conn.set_trace_callback(statements.append)
        try:
            await run()
        finally:
            store._conn.set_trace_callback(None)
        _assert_opens_with_the_write_lock(statements, what=what)

    await _recorded("add (insert)", lambda: store.add(_semantic("fresh", "tea")))
    await _recorded("add (overwrite)", lambda: store.add(_semantic("seed", "cocoa")))
    await _recorded(
        "write_atomic",
        lambda: store.write_atomic(
            [MemoryWrite(record=_semantic("batched", "juice"), mode=MemoryWriteMode.UPSERT)]
        ),
    )
    await _recorded("delete (present)", lambda: store.delete("fresh"))
    await _recorded("delete (absent)", lambda: store.delete("no-such-record"))
    await _recorded("purge_expired (nothing to purge)", store.purge_expired)
    await _recorded("clear", store.clear)


async def test_delete_removes_record_and_reports_existence(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("1", "a fact"))

    assert await store.delete("1") is True
    assert await store.get("1") is None
    assert await store.search("fact") == []  # vector row gone too
    assert await store.delete("1") is False  # already gone


async def test_clear_removes_all_and_returns_count(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("1", "one"))
    await store.add(_semantic("2", "two"))

    assert await store.clear() == 2
    assert await store.get("1") is None
    assert await store.search("one") == []
    assert await store.clear() == 0


async def test_export_returns_live_records_only(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("live", "still valid"))
    await store.add(_semantic("dead", "gone", expires_at=datetime(2026, 1, 2, tzinfo=UTC)))

    exported = await store.export()

    assert [r.id for r in exported] == ["live"]
    assert isinstance(exported[0], SemanticMemory)  # typed, not a blob


async def test_expired_records_are_hidden_from_get_and_search(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("1", "coffee fact", expires_at=datetime(2026, 1, 2, tzinfo=UTC)))
    await store.add(_semantic("2", "coffee fact live"))

    assert await store.get("1") is None
    assert [r.id for r in await store.search("coffee")] == ["2"]  # expired one filtered out


async def test_a_naive_injected_clock_is_the_subsystems_error(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    """Inverted by ADR-0026: the reading used to be attributed UTC here.

    This seam never reaches a `core` validator — the reading becomes a float
    through ``timestamp()`` — so the producer guard is the whole protection.
    """
    store = make_store(now=lambda: datetime(2026, 6, 1))  # noqa: DTZ001  naive clock
    await store.add(_semantic("1", "coffee", expires_at=datetime(2026, 1, 2, tzinfo=UTC)))

    with pytest.raises(MemoryStoreError, match="SqliteMemoryStore"):
        await store.get("1")
    with pytest.raises(MemoryStoreError, match="SqliteMemoryStore"):
        await store.search("coffee")


async def test_purge_expired_removes_only_expired_and_returns_count(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("live", "keeps"))
    await store.add(_semantic("dead", "goes", expires_at=datetime(2026, 1, 2, tzinfo=UTC)))

    assert await store.purge_expired() == 1
    assert await store.get("live") is not None
    assert await store.purge_expired() == 0


def _write_legacy_db(
    path: Path, records: list[MemoryRecord], *, with_expires_at: bool = False
) -> None:
    """Create a legacy database whose ``records`` table predates a column.

    ``with_expires_at=False`` is the pre-ADR-0007 shape (neither ``expires_at``
    nor ``valid_until``). ``with_expires_at=True`` is the intermediate
    post-ADR-0007, pre-ADR-0045 shape: ``expires_at`` present, ``valid_until``
    absent — the table variant whose ``valid_until`` migration must run on its own.
    """
    legacy = sqlite3.connect(path)
    legacy.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    legacy.executemany(
        "INSERT INTO meta(key, value) VALUES (?, ?)",
        [("embedding_model", "hashing-8"), ("dimensions", "8")],
    )
    if with_expires_at:
        legacy.execute(
            "CREATE TABLE records(rowid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, "
            "kind TEXT NOT NULL, data TEXT NOT NULL, expires_at REAL)"
        )
        legacy.executemany(
            "INSERT INTO records(id, kind, data, expires_at) VALUES (?, ?, ?, ?)",
            [(r.id, r.kind, r.model_dump_json(), _epoch_or_none(r.expires_at)) for r in records],
        )
    else:
        legacy.execute(
            "CREATE TABLE records(rowid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, "
            "kind TEXT NOT NULL, data TEXT NOT NULL)"
        )
        legacy.executemany(
            "INSERT INTO records(id, kind, data) VALUES (?, ?, ?)",
            [(r.id, r.kind, r.model_dump_json()) for r in records],
        )
    legacy.commit()
    legacy.close()


def _epoch_or_none(instant: datetime | None) -> float | None:
    return instant.timestamp() if instant is not None else None


def _micros(instant: datetime) -> int:
    """Exact integer microsecond UTC epoch, mirroring the store's representation."""
    delta = instant - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


async def test_migration_adds_expires_at_column_and_accepts_writes(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    _write_legacy_db(db, [])

    store = SqliteMemoryStore(path=db, embedder=HashingEmbedder(dimensions=8), now=_fixed_now)
    try:
        columns = {row[1] for row in store._conn.execute("PRAGMA table_info(records)")}
        assert "expires_at" in columns
        await store.add(_semantic("1", "post-migration write"))
        assert await store.get("1") is not None
    finally:
        store.close()


async def test_migration_backfills_expiry_so_legacy_expired_stays_forgotten(
    tmp_path: Path,
) -> None:
    # Pre-ADR-0007 records carry expires_at only inside their JSON. Migration must
    # backfill it, or an already-expired legacy memory would come back to life.
    db = tmp_path / "legacy.db"
    _write_legacy_db(
        db,
        [
            _semantic("expired", "legacy expired", expires_at=datetime(2026, 1, 2, tzinfo=UTC)),
            _semantic("live", "legacy live"),
        ],
    )

    store = SqliteMemoryStore(path=db, embedder=HashingEmbedder(dimensions=8), now=_fixed_now)
    try:
        assert await store.get("expired") is None  # backfilled deadline honoured
        assert await store.get("live") is not None
        assert [r.id for r in await store.export()] == ["live"]
        assert await store.purge_expired() == 1
    finally:
        store.close()


def _valid_until_column(store: SqliteMemoryStore, record_id: str) -> int | None:
    """Read the raw ``records.valid_until`` column for a record, bypassing decode.

    The migration's whole job is to *populate this column* from the JSON blob, so
    a test of the backfill must assert the column itself — ``get``/``search``
    decode ``valid_from`` from JSON and could pass with the column empty, and
    ``search`` over an unpopulated ``vec_records`` yields nothing regardless. The
    column is an integer microsecond epoch (issue #289).
    """
    row = store._conn.execute(
        "SELECT valid_until FROM records WHERE id = ?", (record_id,)
    ).fetchone()
    assert row is not None
    return cast("int | None", row[0])


async def test_migration_backfills_valid_until_column_from_json(tmp_path: Path) -> None:
    # A pre-ADR-0045 database carries a record's closed window only in its JSON
    # blob; search filters valid_until from the column, so migration must backfill
    # it or a retired legacy belief would resurface in search (ADR-0045 §9). Assert
    # the column itself, not a read path that reads the window back out of JSON.
    retired_deadline = datetime(2026, 1, 2, tzinfo=UTC)
    db = tmp_path / "legacy.db"
    _write_legacy_db(
        db,
        [
            _semantic(
                "retired", "legacy coffee retired", validity=Validity(valid_until=retired_deadline)
            ),
            _semantic("live", "legacy coffee live"),
        ],
    )

    store = SqliteMemoryStore(path=db, embedder=HashingEmbedder(dimensions=8), now=_fixed_now)
    try:
        columns = {row[1] for row in store._conn.execute("PRAGMA table_info(records)")}
        assert "valid_until" in columns
        # The backfill populated the column for the retired record and left the
        # live one NULL (= open) — the property search's column pre-filter relies on.
        assert _valid_until_column(store, "retired") == _micros(retired_deadline)
        assert _valid_until_column(store, "live") is None
        # And the read paths honour it: retired is hidden from get, retained by export.
        assert await store.get("retired") is None
        assert await store.get("live") is not None
        assert {r.id for r in await store.export()} == {"retired", "live"}
    finally:
        store.close()


async def test_migration_adds_valid_until_to_a_post_expires_at_table(
    tmp_path: Path,
) -> None:
    # The intermediate shape: expires_at already present, valid_until absent. Only
    # the valid_until migration block should run, and it must backfill the closed
    # window from JSON just the same.
    retired_deadline = datetime(2026, 1, 2, tzinfo=UTC)
    db = tmp_path / "intermediate.db"
    _write_legacy_db(
        db,
        [
            _semantic(
                "retired", "legacy coffee retired", validity=Validity(valid_until=retired_deadline)
            ),
            _semantic("live", "legacy coffee live"),
        ],
        with_expires_at=True,
    )

    store = SqliteMemoryStore(path=db, embedder=HashingEmbedder(dimensions=8), now=_fixed_now)
    try:
        types = {row[1]: row[2] for row in store._conn.execute("PRAGMA table_info(records)")}
        assert {"expires_at", "valid_until"} <= types.keys()
        # Both columns are INTEGER µs epochs: the legacy REAL expires_at was
        # re-created with INTEGER affinity (issue #289), not left as REAL — the
        # affinity, not just the value, is what a far-future boundary depends on.
        assert types["expires_at"] == "INTEGER"
        assert types["valid_until"] == "INTEGER"
        # The valid_until block ran on its own and backfilled the column.
        assert _valid_until_column(store, "retired") == _micros(retired_deadline)
        assert _valid_until_column(store, "live") is None
        assert await store.get("retired") is None
        assert {r.id for r in await store.export()} == {"retired", "live"}
    finally:
        store.close()


async def test_list_beliefs_orders_and_pages_migration_era_rows(tmp_path: Path) -> None:
    # Store-specific mechanics the shared suite cannot reach: rows written before
    # the lifecycle columns existed. ``list_beliefs`` pre-filters expiry and
    # ``valid_until`` from those columns, so a migrated row is only ordered and
    # paged correctly if the rebuild backfilled them — and it sorts on
    # ``last_updated``, which lives in the JSON blob the rebuild copies verbatim.
    db = tmp_path / "legacy.db"
    _write_legacy_db(
        db,
        [
            _semantic("newest", "legacy c", last_updated=_WHEN + timedelta(hours=2)),
            _semantic("middle", "legacy b", last_updated=_WHEN + timedelta(hours=1)),
            _semantic("oldest", "legacy a", last_updated=_WHEN),
            _semantic("gone", "legacy expired", expires_at=_WHEN, last_updated=_NOW),
            _semantic(
                "retired",
                "legacy retired",
                validity=Validity(valid_until=_WHEN),
                last_updated=_NOW,
            ),
        ],
    )

    store = SqliteMemoryStore(path=db, embedder=HashingEmbedder(dimensions=8), now=_fixed_now)
    try:
        # The two unreadable rows carry the *newest* stamps, so they sort ahead of
        # the cut: a page of 2 is short unless both axes are applied before it.
        assert [r.id for r in await store.list_beliefs(limit=2)] == ["newest", "middle"]
        assert [r.id for r in await store.list_beliefs(limit=2, offset=2)] == ["oldest"]
        assert {r.id for r in await store.export()} == {"newest", "middle", "oldest", "retired"}
    finally:
        store.close()


async def test_list_beliefs_orders_instants_of_differing_precision_chronologically(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    # The reason this store does not sort in SQL. ``last_updated`` is stored only
    # as ISO text inside the JSON blob, and pydantic emits "...:00Z" for a whole
    # second but "...:00.000001Z" otherwise — and '.' < 'Z', so a text ORDER BY
    # (or a json_extract one) puts the *later* instant last. Chronologically the
    # microsecond one is newer and must lead.
    store = make_store()
    whole = datetime(2026, 3, 1, tzinfo=UTC)
    await store.add(_semantic("whole", "a", last_updated=whole))
    await store.add(_semantic("micro", "b", last_updated=whole + timedelta(microseconds=1)))

    assert [r.id for r in await store.list_beliefs()] == ["micro", "whole"]


async def test_list_beliefs_kind_filter_reaches_the_sql_pre_filter(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    # The kind filter is the one predicate this read binds into the SQL, as an
    # ``IN`` list whose placeholder count varies with the filter. Two kinds at
    # once is what a single-placeholder mistake would break.
    store = make_store()
    await store.add(_semantic("s", "a fact"))
    await store.add(_preference("p", "a preference"))

    both = await store.list_beliefs(kinds=[MemoryKind.SEMANTIC, MemoryKind.PREFERENCE])
    one = await store.list_beliefs(kinds=[MemoryKind.PREFERENCE])

    assert {r.id for r in both} == {"s", "p"}
    assert [r.id for r in one] == ["p"]


async def _write_real_schema_db(
    path: Path, records: list[MemoryRecord], embedder: HashingEmbedder
) -> None:
    """Create the pre-#289 installed schema: both lifecycle columns ``REAL``.

    Unlike :func:`_write_legacy_db` this builds the *complete* prior on-disk
    shape — ``expires_at REAL, valid_until REAL`` — with a populated
    ``vec_records`` virtual table, so a migration test can prove the affinity
    rebuild carries each row's vector forward (its rowid preserved) and search
    still finds it. Lifecycle deadlines are written through ``timestamp()``, the
    lossy ``REAL`` representation the rebuild then corrects from JSON.
    """
    conn = sqlite3.connect(path)
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.executemany(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            [("embedding_model", embedder.model_id), ("dimensions", str(embedder.dimensions))],
        )
        conn.execute(
            "CREATE TABLE records(rowid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, "
            "kind TEXT NOT NULL, data TEXT NOT NULL, expires_at REAL, valid_until REAL)"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE vec_records "
            f"USING vec0(embedding float[{embedder.dimensions}] distance_metric=cosine)"
        )
        vectors = await embedder.embed([r.content for r in records])
        for record, vector in zip(records, vectors, strict=True):
            cursor = conn.execute(
                "INSERT INTO records(id, kind, data, expires_at, valid_until) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.kind,
                    record.model_dump_json(),
                    _epoch_or_none(record.expires_at),
                    _epoch_or_none(record.validity.valid_until),
                ),
            )
            conn.execute(
                "INSERT INTO vec_records(rowid, embedding) VALUES (?, ?)",
                (cursor.lastrowid, sqlite_vec.serialize_float32(list(vector))),
            )
        conn.commit()
    finally:
        conn.close()


async def test_migration_rebuilds_a_full_real_schema_preserving_vectors(tmp_path: Path) -> None:
    # issue #289, the actual pre-change installed schema: BOTH lifecycle columns
    # REAL, with populated vec_records. The rebuild must flip both to INTEGER µs,
    # backfill exact epochs, and carry each rowid forward so the vector join
    # survives — a far-future record stays live AND still matches in search, where
    # the lossy REAL column would have hidden it and a lost vector would drop it.
    embedder = HashingEmbedder(dimensions=8)
    far_future = datetime(9999, 1, 1, tzinfo=UTC)
    just_before = datetime(9998, 12, 31, 23, 59, 59, 999_999, tzinfo=UTC)  # 1 µs earlier
    records = [
        _semantic("live", "coffee beans", validity=Validity(valid_until=far_future)),
        _semantic("plain", "coffee grounds"),
    ]
    db = tmp_path / "real.db"
    await _write_real_schema_db(db, records, embedder)

    store = SqliteMemoryStore(path=db, embedder=embedder, now=lambda: just_before)
    try:
        types = {row[1]: row[2] for row in store._conn.execute("PRAGMA table_info(records)")}
        assert types["expires_at"] == "INTEGER"  # affinity flipped, not left REAL
        assert types["valid_until"] == "INTEGER"
        # The far-future deadline is exact after the rebuild (a REAL column would
        # have rounded it and hidden the record one µs early).
        assert _valid_until_column(store, "live") == _micros(far_future)
        assert await store.get("live") is not None  # still live: now < valid_until
        # The carried-forward vectors still match — the rowid join survived.
        assert {r.id for r in await store.search("coffee")} == {"live", "plain"}
    finally:
        store.close()


async def test_migration_rolls_back_a_rebuild_that_hits_a_corrupt_row(tmp_path: Path) -> None:
    # A corrupt legacy JSON blob makes the backfill raise mid-rebuild. Because the
    # rewrite runs in an explicit transaction, the schema swap must roll back whole
    # — never leave INTEGER columns with un-backfilled NULLs that a reopen would
    # skip, silently resurrecting expired rows (issue #289 review, blocker 1).
    embedder = HashingEmbedder(dimensions=8)
    good = _semantic("good", "coffee", expires_at=datetime(2026, 1, 2, tzinfo=UTC))
    db = tmp_path / "corrupt.db"
    await _write_real_schema_db(db, [good], embedder)
    legacy = sqlite3.connect(db)
    legacy.execute("UPDATE records SET data = ? WHERE id = ?", ("not-json", "good"))
    legacy.commit()
    legacy.close()

    with pytest.raises(MemoryStoreError):
        SqliteMemoryStore(path=db, embedder=embedder, now=_fixed_now)

    # The rebuild rolled back: the original REAL schema is intact, so a fixed
    # process could migrate cleanly later rather than being stuck half-swapped.
    check = sqlite3.connect(db)
    try:
        types = {row[1]: row[2] for row in check.execute("PRAGMA table_info(records)")}
        assert types["expires_at"] == "REAL"  # unchanged — the swap did not commit
        assert types["valid_until"] == "REAL"
        assert not list(
            check.execute("SELECT name FROM sqlite_master WHERE name='records_migrated'")
        )
    finally:
        check.close()


# --- the subject axis: the column and its migration (ADR-0100 §8) ------------


def _subject_column(store: SqliteMemoryStore, record_id: str) -> str | None:
    """Read the raw ``records.about_person`` column, bypassing the JSON decode.

    The column is what §8's migration is *about*, and nothing reads it yet — so a
    case asserting through ``get`` would pass with the column empty, since every
    read decodes the record from the blob. Asserting the column directly is the
    only way to see the write path populating it.
    """
    row = store._conn.execute(
        "SELECT about_person FROM records WHERE id = ?", (record_id,)
    ).fetchone()
    return None if row is None else row[0]


def _write_pre_subject_db(path: Path, records: list[MemoryRecord]) -> None:
    """Create a database on the *current* epoch schema but without the subject column.

    The shape a build immediately before ADR-0100 wrote: both lifecycle columns
    already ``INTEGER`` microsecond epochs, so the rebuild path correctly declines
    to run, and ``about_person`` absent. It is the case a migration keyed only on
    the epoch check would silently skip.
    """
    legacy = sqlite3.connect(path)
    legacy.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    legacy.executemany(
        "INSERT INTO meta(key, value) VALUES (?, ?)",
        [("embedding_model", "hashing-8"), ("dimensions", "8")],
    )
    legacy.execute(
        "CREATE TABLE records(rowid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, "
        "kind TEXT NOT NULL, data TEXT NOT NULL, "
        "expires_at INTEGER, valid_until INTEGER)"
    )
    legacy.executemany(
        "INSERT INTO records(id, kind, data, expires_at, valid_until) VALUES (?, ?, ?, NULL, NULL)",
        [(r.id, r.kind, r.model_dump_json()) for r in records],
    )
    legacy.commit()
    legacy.close()


async def test_a_stated_subject_round_trips_and_reaches_its_column(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    """The record carries the subject, and so does the column beside it.

    The blob is the truth — every read decodes from it — and the column is the
    derived index ADR-0101 will query, exactly the arrangement ``expires_at`` and
    ``valid_until`` already have.
    """
    store = make_store()
    stored = SemanticMemory(
        id="1",
        content="prefers a window seat",
        fact="prefers a window seat",
        about_person="Marta",
        provenance=_provenance(),
    )

    await store.add(stored)

    got = await store.get("1")
    assert got is not None
    assert got.about_person == "Marta"
    assert _subject_column(store, "1") == "Marta"


async def test_the_subject_column_keeps_the_label_verbatim(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    """Nothing between the user and the column normalises a label (ADR-0100 §6)."""
    store = make_store()
    await store.add(
        SemanticMemory(
            id="1",
            content="c",
            fact="c",
            about_person="  marta  ",
            provenance=_provenance(),
        )
    )

    assert _subject_column(store, "1") == "  marta  "


async def test_an_unstated_subject_leaves_the_column_null(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("1", "the office moved"))

    assert _subject_column(store, "1") is None


async def test_an_overwrite_rewrites_the_subject_column(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    """An upsert rewrites every column, this one included — in both directions.

    Clearing it back to ``NULL`` is the half a partial ``UPDATE`` would get wrong,
    and it is the one that matters: a stale label left behind would make the
    column disagree with the blob, and ADR-0101's query would then answer from a
    subject the record no longer states.
    """
    store = make_store()
    await store.add(
        SemanticMemory(
            id="1", content="c", fact="c", about_person="Marta", provenance=_provenance()
        )
    )

    await store.add(SemanticMemory(id="1", content="c", fact="c", provenance=_provenance()))

    assert _subject_column(store, "1") is None
    got = await store.get("1")
    assert got is not None
    assert got.about_person is None


async def test_migration_adds_the_subject_column_to_a_pre_subject_table(
    tmp_path: Path,
) -> None:
    """A nullable column, backfilled ``NULL``, on a table already on the epochs.

    ``NULL`` is the *right* value rather than a placeholder: a record written
    before the field states no subject, and ADR-0100 §8 forbids inferring one for
    it from content, from ``participants`` or by asking a model. The existing rows
    must survive, because this is an ``ALTER`` on a table the rebuild path
    deliberately does not touch.
    """
    db = tmp_path / "pre-subject.db"
    _write_pre_subject_db(db, [_semantic("legacy", "written before the field existed")])

    store = SqliteMemoryStore(path=db, embedder=HashingEmbedder(dimensions=8), now=_fixed_now)
    try:
        columns = {row[1] for row in store._conn.execute("PRAGMA table_info(records)")}
        assert "about_person" in columns
        assert _subject_column(store, "legacy") is None
        assert {r.id for r in await store.export()} == {"legacy"}
        # And the upgraded table takes a write that states one.
        await store.add(
            SemanticMemory(
                id="new", content="c", fact="c", about_person="Marta", provenance=_provenance()
            )
        )
        assert _subject_column(store, "new") == "Marta"
    finally:
        store.close()


async def test_the_rebuild_path_also_produces_the_subject_column(tmp_path: Path) -> None:
    """A table old enough to need the rebuild arrives with the column too.

    The two migrations are ordered rather than independent: the rebuild recreates
    the table, so a column added before it would be dropped. Asserting the oldest
    shape is what makes the ordering observable — a pre-ADR-0007 table has neither
    lifecycle column, so it takes the rebuild and must come out with all three.
    """
    db = tmp_path / "ancient.db"
    _write_legacy_db(db, [_semantic("legacy", "written long before the field")])

    store = SqliteMemoryStore(path=db, embedder=HashingEmbedder(dimensions=8), now=_fixed_now)
    try:
        columns = {row[1] for row in store._conn.execute("PRAGMA table_info(records)")}
        assert {"expires_at", "valid_until", "about_person"} <= columns
        assert _subject_column(store, "legacy") is None
        assert {r.id for r in await store.export()} == {"legacy"}
    finally:
        store.close()


async def test_export_wraps_corrupt_stored_record(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("1", "fine"))
    store._conn.execute("UPDATE records SET data = ? WHERE id = ?", ("not-json", "1"))
    store._conn.commit()

    with pytest.raises(MemoryStoreError, match="could not be decoded"):
        await store.export()


async def test_persists_across_reopen(make_store: Callable[..., SqliteMemoryStore]) -> None:
    store = make_store()
    await store.add(_semantic("1", "durable memory"))
    store.close()

    reopened = make_store()
    got = await reopened.get("1")
    assert got is not None
    assert got.content == "durable memory"


async def test_reopening_with_different_embedder_raises(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    """The refusal stands, and it is a **deployment** fault (ADR-0083 §6).

    What is detected and when is unchanged from ADR-0006 §4 and ADR-0024 §2 —
    only the class is, so an entry point can map "this build cannot serve this
    state" to a stay-down exit without matching on the message string. The
    assertion pins both halves: the new class, and that it is deliberately *not*
    a ``MemoryStoreError``, which is the distinction the hub's exit-code mapping
    rests on.
    """
    store = make_store(dimensions=256)
    await store.add(_semantic("1", "x"))
    store.close()

    with pytest.raises(IncompatibleStateError, match="re-embedding is required") as caught:
        make_store(dimensions=128)

    assert not isinstance(caught.value, MemoryStoreError)
    assert caught.value.expected == "embedding_model='hashing-128'"
    assert caught.value.found == "embedding_model='hashing-256'"
    assert "re-embed" in caught.value.operator_action


def test_database_file_is_owner_only(
    make_store: Callable[..., SqliteMemoryStore], tmp_path: Path
) -> None:
    make_store()
    mode = (tmp_path / "memory.db").stat().st_mode & 0o777
    assert mode == 0o600


def test_a_journal_opened_during_setup_is_owner_only(
    make_store: Callable[..., SqliteMemoryStore],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0004 §4 reaches the sidecars, and reaches them from the first write (#451).

    SQLite copies the *database file's* mode onto every rollback journal it
    creates for it, so restricting the file after the schema is built and migrated
    leaves every journal opened in between carrying the process umask — and an
    interrupted write leaves that journal on disk holding Tier 1 pages beside a
    ``0600`` base file.

    Observed **inside** ``_setup`` rather than after it, because that is the only
    place the difference is visible: by the time the constructor returns, the
    ordering has stopped mattering and a journal provoked afterwards inherits
    ``0600`` under either one. The hook is ``_verify_or_init_meta``, whose ``meta``
    insert opens the transaction whose journal is asserted here; on the unfixed
    ordering that journal is ``0644``.

    The file is pre-created ``0644`` so the case does not depend on the runner's
    umask — and because reopening an existing store is the common path anyway.
    """
    path = tmp_path / "memory.db"
    path.touch()
    path.chmod(0o644)
    observed: list[int | None] = []
    original = SqliteMemoryStore._verify_or_init_meta

    def observing(store: SqliteMemoryStore, conn: sqlite3.Connection) -> None:
        original(store, conn)
        observed.append(_journal_mode(path))

    monkeypatch.setattr(SqliteMemoryStore, "_verify_or_init_meta", observing)

    make_store()

    assert observed[0] is not None, "setup should have opened a journal"
    assert observed == [0o600]


def test_a_sidecar_that_was_already_there_is_restricted_at_open(
    make_store: Callable[..., SqliteMemoryStore], tmp_path: Path
) -> None:
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
    path = tmp_path / "memory.db"
    make_store().close()
    sidecars = [Path(f"{path}{suffix}") for suffix in ("-wal", "-shm")]
    for sidecar in sidecars:
        sidecar.touch()
        sidecar.chmod(0o644)

    make_store()

    assert [each.stat().st_mode & 0o777 for each in sidecars] == [0o600, 0o600]


class TestSqliteMemoryStoreContract(MemoryStoreContract):
    """Runs SqliteMemoryStore through the shared MemoryStore conformance suite.

    Inherits this module's ``integration`` mark (native sqlite-vec + filesystem);
    ``make_store`` closes the store on teardown.
    """

    @pytest.fixture
    def store(self, make_store: Callable[..., SqliteMemoryStore]) -> MemoryStore:
        return make_store()

    @pytest.fixture
    def store_factory(
        self, make_store: Callable[..., SqliteMemoryStore]
    ) -> Callable[[Callable[[], datetime]], MemoryStore]:
        return lambda now: make_store(now=now)

    @contextlib.asynccontextmanager
    async def store_suspended_mid_write(
        self,
    ) -> AsyncIterator[SuspendedMidWrite[MemoryStore]]:
        """Park a named write's worker thread inside the connection's turn.

        ``arm(operation)`` wraps that operation's ``_<operation>_sync`` — inside
        ``async with self._lock`` and inside the ``to_thread`` the event loop
        cannot interrupt, which is exactly where ADR-0054's bug lived — so the
        first worker to reach it blocks and every later one runs free. Each
        distinct lock site is a separate place the bug can reappear (#370), and
        the sync-method suffix matches the operation name (``add`` →
        ``_add_sync``, ``write_atomic`` → ``_write_atomic_sync``). Blocking there
        is what makes the case deterministic: left to run, a commit finishes in
        microseconds and whether the second caller arrives while the worker still
        holds the connection would be a race, so the invariant would be exercised
        only sometimes.

        Its own store on its own connection, not the ``store`` fixture's: the
        suspended worker is parked for the length of the case, and sharing would
        make an unrelated failure hang instead of fail.
        """
        store = SqliteMemoryStore(path=":memory:", embedder=HashingEmbedder(dimensions=8))
        log = ResourceLog()
        suspension = ThreadSuspension()

        def arm(operation: str) -> SuspendedCall:
            original = getattr(store, f"_{operation}_sync")
            armed = threading.Event()

            def blocking(*args: object) -> object:
                with log.inside():  # the span the connection is genuinely in use for
                    if not armed.is_set():  # the first worker only; later ones run free
                        armed.set()
                        suspension.hold()
                    return original(*args)

            setattr(store, f"_{operation}_sync", blocking)
            return suspension

        try:
            yield SuspendedMidWrite(store=store, log=log, arm=arm)
        finally:
            suspension.release()
            # An implementation that released the connection early leaves a
            # worker still using it; closing under that is a native crash rather
            # than a reported failure, so give the worker a turn to unwind and
            # let the assertion above be the thing that speaks.
            await asyncio.sleep(0.05)
            store.close()

    @contextlib.asynccontextmanager
    async def store_suspended_at_its_first_await(
        self,
    ) -> AsyncIterator[tuple[MemoryStore, Callable[[str], SuspendedCall]]]:
        """Park the named call at its own first ``await`` — which is not one place.

        A different position from ``store_suspended_mid_write`` above, and
        deliberately so. ADR-0060's hook goes *inside the connection*, which for
        this store is after the embedding; ADR-0065's must be at the method's own
        first suspension point. For ``add`` and ``write_atomic`` that is exactly
        the boundary the #286 tear straddled — the content read for the vector
        before it, the id and the JSON read after — so a hook at the later position
        would let the mutation land past every read, observe one coherent version,
        and certify the bug.

        **Three of the five operations suspend on the embedder and two do not**,
        which is why the widened hook takes the operation's name (#436).
        ``add``, ``write_atomic`` and ``search`` all embed before they touch the
        connection, so the injected ``Embedder`` is their first ``await``.
        ``list_beliefs`` and ``get_many`` embed nothing: the first ``await`` of each
        is ``async with self._lock``, so the lever there is the lock itself, wrapped
        so one acquisition can be held at the door. Suspending it anywhere later — inside
        ``_list_beliefs_sync``, say — would put the mutation past the point a
        non-conforming implementation would have read ``bands``, which is the
        entry-side mistake ADR-0065 §3 warns about, in mirror image.

        Arming is deferred to ``arm`` because the read cases must seed the store
        first, and every seeding ``add`` embeds: a hook armed at construction would
        spend its one suspension on a precondition.

        Its own store on its own connection, like the hook above, so a failure
        leaves nothing parked on the ``store`` fixture's.
        """
        embedder = _GatedEmbedder(HashingEmbedder(dimensions=8))
        store = SqliteMemoryStore(path=":memory:", embedder=embedder, now=_fixed_now)
        lock = _GatedLock(store._lock)

        def arm(operation: str) -> SuspendedCall:
            if operation in {"list_beliefs", "get_many"}:
                # Installed only when it is needed, so every other case runs on the
                # store's own lock. `_lock` is typed `asyncio.Lock`; this stands in
                # for one and is only ever entered through `async with`.
                store._lock = lock  # type: ignore[assignment]
                lock.arm()
                return lock
            embedder.arm()
            return embedder

        try:
            yield store, arm
        finally:
            embedder.release()
            lock.release()
            store.close()


class _GatedEmbedder:
    """An ``Embedder`` that parks its next call, once armed, until the suite releases it.

    ``FakeEmbedder``/``HashingEmbedder`` cannot suspend, and the first ``await`` of
    every store method that embeds is that embedding, so the input-observation
    cases need one that can. Only the call after ``arm`` is gated: the cases seed
    the store before arming and read it back afterwards, and both of those embed
    too.
    """

    def __init__(self, delegate: Embedder) -> None:
        """Wrap ``delegate``; unarmed, so nothing suspends until :meth:`arm`."""
        self._delegate = delegate
        self._armed = False
        self._entered = asyncio.Event()
        self._released = asyncio.Event()

    def arm(self) -> None:
        """Make the next :meth:`embed` suspend."""
        self._armed = True

    @property
    def model_id(self) -> str:
        """The wrapped embedder's identifier."""
        return self._delegate.model_id

    @property
    def dimensions(self) -> int:
        """The wrapped embedder's vector length."""
        return self._delegate.dimensions

    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        """Suspend on the first call, then delegate."""
        if self._armed:
            self._armed = False
            self._entered.set()
            await self._released.wait()
        return await self._delegate.embed(texts)

    async def reached(self) -> None:
        """Wait until the gated call has arrived."""
        async with asyncio.timeout(_GATE_SECONDS):
            await self._entered.wait()

    def release(self) -> None:
        """Let the gated call finish; idempotent."""
        self._released.set()


class _GatedLock:
    """The store's ``asyncio.Lock``, wrapped so one acquisition can be held at the door.

    ``list_beliefs`` is the one operation the input-observation cases drive that
    never embeds, so its first ``await`` is the lock rather than the embedder. The
    suspension goes *before* ``acquire``, not after: a conforming implementation
    has materialised both filters on its first executed lines and cannot be reached
    by the mutation, while one that read them after taking the lock would be.
    """

    def __init__(self, delegate: asyncio.Lock) -> None:
        """Wrap ``delegate``; unarmed, so nothing suspends until :meth:`arm`."""
        self._delegate = delegate
        self._armed = False
        self._entered = asyncio.Event()
        self._released = asyncio.Event()

    def arm(self) -> None:
        """Make the next acquisition suspend before it takes the lock."""
        self._armed = True

    async def __aenter__(self) -> None:
        """Suspend if armed, then take the real lock."""
        if self._armed:
            self._armed = False
            self._entered.set()
            await self._released.wait()
        await self._delegate.acquire()

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Release the real lock."""
        self._delegate.release()

    async def reached(self) -> None:
        """Wait until the gated call has arrived."""
        async with asyncio.timeout(_GATE_SECONDS):
            await self._entered.wait()

    def release(self) -> None:
        """Let the gated call take the lock; idempotent."""
        self._released.set()


async def _spin(iterations: int = 50) -> None:
    """Yield to the event loop repeatedly so a pending cancellation can unwind."""
    for _ in range(iterations):
        await asyncio.sleep(0)


async def test_cancelling_a_write_does_not_release_the_connection(tmp_path: Path) -> None:
    """A cancelled write must not free the lock while its worker thread runs (ADR-0054).

    The bug: ``asyncio.to_thread`` cannot interrupt a running worker, so if the
    awaiting coroutine were simply cancelled the ``async with self._lock`` would
    unwind and release the lock while the worker was still using the shared
    connection — letting a second caller use the same connection concurrently,
    which SQLite refuses. This blocks a worker mid-``add``, cancels the awaiting
    task, and asserts the lock stays held until the worker finishes, then that a
    second write lands on an intact connection.
    """
    store = SqliteMemoryStore(path=tmp_path / "cancel.db", embedder=HashingEmbedder(dimensions=8))
    entered = threading.Event()
    release = threading.Event()
    original_add = store._add_sync

    def blocking_add(record: MemoryRecord, vector: Embedding) -> None:
        # Block only the first worker (record "a"): it enters, signals, and waits
        # inside the connection's turn until the test lets it finish.
        if not entered.is_set():
            entered.set()
            if not release.wait(timeout=5):  # pragma: no cover - only on a hang
                msg = "the blocked worker was never released"
                raise AssertionError(msg)
        original_add(record, vector)

    store._add_sync = blocking_add  # type: ignore[method-assign]
    try:
        first = asyncio.ensure_future(store.add(_semantic("a", "alpha")))
        assert await asyncio.to_thread(entered.wait, 5), "worker never entered"
        assert store._lock.locked()  # the worker holds the connection under the lock

        first.cancel()
        await _spin()
        # The invariant: cancellation did NOT release the lock — the worker thread
        # is still running, so the connection is still exclusively held. On the
        # pre-ADR-0054 code the lock would already be free here.
        assert store._lock.locked()

        # A second write queues on the lock; it must not begin on the shared
        # connection while the first worker is still running.
        second = asyncio.ensure_future(store.add(_semantic("b", "bravo")))
        await _spin()
        assert not second.done()
        assert store._lock.locked()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await second  # must not raise "recursive use of cursors"/locked

        # The connection is intact: the deferred-to-completion first write did
        # commit, and the second landed cleanly on top of it.
        assert await store.get("a") is not None
        assert await store.get("b") is not None
        assert not store._lock.locked()
    finally:
        release.set()
        store.close()


async def test_cancellation_takes_precedence_over_a_worker_error(tmp_path: Path) -> None:
    """A cancelled call whose worker then fails still raises CancelledError (ADR-0054).

    Once a cancellation has been absorbed, the worker's own failure is moot: the
    caller asked to cancel, so it must see ``CancelledError`` — not the store error
    the worker happened to raise as it finished. And the connection must survive
    both, so the next call lands cleanly.
    """
    store = SqliteMemoryStore(path=tmp_path / "cancel.db", embedder=HashingEmbedder(dimensions=8))
    entered = threading.Event()
    release = threading.Event()

    def failing_add(record: MemoryRecord, vector: Embedding) -> None:
        entered.set()
        if not release.wait(timeout=5):  # pragma: no cover - only on a hang
            msg = "the blocked worker was never released"
            raise AssertionError(msg)
        raise MemoryStoreError("worker failed as it finished")

    store._add_sync = failing_add  # type: ignore[method-assign]
    try:
        first = asyncio.ensure_future(store.add(_semantic("a", "alpha")))
        assert await asyncio.to_thread(entered.wait, 5), "worker never entered"
        first.cancel()
        await _spin()
        assert store._lock.locked()

        release.set()
        # The worker raises MemoryStoreError as it finishes, but the caller was
        # cancelled: it must observe the cancellation, not the store error.
        with pytest.raises(asyncio.CancelledError):
            await first

        # The connection is intact despite the worker's error under cancellation.
        del store._add_sync  # restore the real implementation
        assert await store.add(_semantic("b", "bravo")) == "b"
        assert await store.get("b") is not None
        assert not store._lock.locked()
    finally:
        release.set()
        store.close()


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
