"""The durable diagnostic record, run through both suites and pinned on its own file (§6).

Every case here opens a real directory, so the module is ``integration`` (CONTRIBUTING
→ Testing). The suites prove the Protocols; the cases below them pin what only a file
has: its name, its line shape, its owner-only modes, its byte bound and its truncation
marker (ADR-0314 §2:3, §6).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import stat
import threading
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import structlog
from diagnostic_contracts import DiagnosticRetentionContract, DiagnosticSinkContract

from ai_assistant.core.diagnostics import DIAGNOSTIC_NOT_WRITTEN
from ai_assistant.core.errors import DiagnosticRecordError
from ai_assistant.core.types import DiagnosticEntry, DiagnosticKind, DiagnosticSource
from ai_assistant.evaluation import FileDiagnosticRecord
from ai_assistant.evaluation import diagnostic_record as store_module
from ai_assistant.evaluation.diagnostic_record import (
    FOLLOW_UP_SUFFIX,
    MIN_FILE_BYTES,
    OBSERVER_SUFFIX,
    SUFFIX,
)
from ai_assistant.testing import diagnostic_entry
from ai_assistant.testing.cancellation import (
    ResourceLog,
    SuspendedCall,
    SuspendedMidWrite,
    ThreadSuspension,
)
from ai_assistant.testing.diagnostics import (
    DEFAULT_DIAGNOSED_ACTIVATION,
    DEFAULT_RECORDED_AT,
    plain_file_name,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import datetime

    from ai_assistant.core.protocols import DiagnosticRetention, DiagnosticSink

pytestmark = pytest.mark.integration

_BOUND = 8 * 1024 * 1024
_SYNC_METHODS = {"write": "_append_sync", "purge_before": "_purge_sync"}


def _lines(path: Path) -> list[dict[str, Any]]:
    """The file's lines as JSON objects — the test reading what the owner would."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _entries(directory: Path, activation_id: str) -> tuple[DiagnosticEntry, ...]:
    if not plain_file_name(activation_id):
        return ()
    path = directory / f"{activation_id}{SUFFIX}"
    if not path.exists():
        return ()
    return tuple(
        DiagnosticEntry.model_validate(one) for one in _lines(path) if "truncated" not in one
    )


@contextlib.asynccontextmanager
async def _suspended(directory: Path) -> AsyncIterator[SuspendedMidWrite[Any]]:
    """Park a named operation's worker inside the store's lock, as the trace store's is."""
    record = FileDiagnosticRecord(directory=directory, file_bytes=_BOUND)
    log = ResourceLog()
    suspension = ThreadSuspension()

    def arm(operation: str) -> SuspendedCall:
        attribute = _SYNC_METHODS[operation]
        original = getattr(record, attribute)
        armed = threading.Event()

        def blocking(*args: object) -> object:
            with log.inside():
                if not armed.is_set():
                    armed.set()
                    suspension.hold()
                return original(*args)

        setattr(record, attribute, blocking)
        return suspension

    try:
        yield SuspendedMidWrite(store=record, log=log, arm=arm)
    finally:
        suspension.release()
        await asyncio.sleep(0.05)


class TestFileDiagnosticSinkContract(DiagnosticSinkContract):
    """Runs the file store through the shared ``DiagnosticSink`` suite."""

    @pytest.fixture
    def sink(self, tmp_path: Path) -> DiagnosticSink:
        return FileDiagnosticRecord(directory=tmp_path / "diagnostics", file_bytes=_BOUND)

    async def recorded(
        self, sink: DiagnosticSink, activation_id: str
    ) -> tuple[DiagnosticEntry, ...]:
        assert isinstance(sink, FileDiagnosticRecord)
        return _entries(sink.directory, activation_id)

    def failing_sink(self) -> DiagnosticSink:
        # A file where the directory should be: every write meets it.
        blocked = Path(self._root) / "diagnostics"
        blocked.write_text("not a directory", encoding="utf-8")
        return FileDiagnosticRecord(directory=blocked, file_bytes=_BOUND)

    @pytest.fixture(autouse=True)
    def _root_for_failing(self, tmp_path: Path) -> None:
        self._root = tmp_path / "failing"
        self._root.mkdir()

    @contextlib.asynccontextmanager
    async def subject_suspended_mid_operation(self) -> AsyncIterator[SuspendedMidWrite[Any]]:
        """Park the write's worker inside the store's lock.

        Yields:
            The harness.
        """
        async with _suspended(self._root / "suspended") as harness:
            yield harness


class TestFileDiagnosticRetentionContract(DiagnosticRetentionContract):
    """Runs the file store through the shared ``DiagnosticRetention`` suite."""

    @pytest.fixture(autouse=True)
    def _root(self, tmp_path: Path) -> None:
        self._base = tmp_path

    @pytest.fixture
    def retention(self, tmp_path: Path) -> DiagnosticRetention:
        return FileDiagnosticRecord(directory=tmp_path / "diagnostics", file_bytes=_BOUND)

    async def hold(
        self, retention: DiagnosticRetention, activation_id: str, last_write: datetime
    ) -> None:
        assert isinstance(retention, FileDiagnosticRecord)
        retention.directory.mkdir(mode=0o700, exist_ok=True)
        path = retention.directory / f"{activation_id}{SUFFIX}"
        path.write_text("{}\n", encoding="utf-8")
        stamp = last_write.timestamp()
        os.utime(path, (stamp, stamp))

    async def remaining(self, retention: DiagnosticRetention) -> frozenset[str]:
        assert isinstance(retention, FileDiagnosticRecord)
        return frozenset(path.name.removesuffix(SUFFIX) for path in retention.directory.iterdir())

    def failing_retention(self) -> DiagnosticRetention:
        blocked = self._base / "blocked"
        blocked.write_text("not a directory", encoding="utf-8")
        return FileDiagnosticRecord(directory=blocked, file_bytes=_BOUND)

    @contextlib.asynccontextmanager
    async def subject_suspended_mid_operation(self) -> AsyncIterator[SuspendedMidWrite[Any]]:
        """Park the sweep's worker inside the store's lock.

        Yields:
            The harness.
        """
        async with _suspended(self._base / "suspended") as harness:
            yield harness


# --- what only the file can be asked ------------------------------------------


async def test_each_activation_is_one_file_of_one_json_object_per_line(tmp_path: Path) -> None:
    """§6:1-§6:2: ``<id>.jsonl``, each line the id, source, kind, instant and body."""
    record = FileDiagnosticRecord(directory=tmp_path / "diagnostics", file_bytes=_BOUND)
    first = diagnostic_entry(body={"text": "line one\nwith a newline"})
    second = diagnostic_entry(source=DiagnosticSource.RECALL, kind=DiagnosticKind.RETURNED)

    await record.write(first)
    await record.write(second)

    path = tmp_path / "diagnostics" / f"{DEFAULT_DIAGNOSED_ACTIVATION}.jsonl"
    lines = _lines(path)
    assert [list(one) for one in lines] == [
        ["activation_id", "source", "kind", "recorded_at", "body"]
    ] * 2
    assert lines[0]["body"] == {"text": "line one\nwith a newline"}
    assert (lines[1]["source"], lines[1]["kind"]) == ("recall", "returned")


async def test_nothing_is_created_before_the_first_write(tmp_path: Path) -> None:
    """A deployment with the record off never gains a directory (§2:1)."""
    FileDiagnosticRecord(directory=tmp_path / "diagnostics", file_bytes=_BOUND)

    assert not (tmp_path / "diagnostics").exists()


async def test_the_directory_and_each_file_are_the_owners_alone(tmp_path: Path) -> None:
    """§2:3: ``0700`` and ``0600``, whatever the process's umask allows."""
    previous = os.umask(0)
    try:
        record = FileDiagnosticRecord(directory=tmp_path / "diagnostics", file_bytes=_BOUND)
        await record.write(diagnostic_entry())
    finally:
        os.umask(previous)

    directory = tmp_path / "diagnostics"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    file_mode = (directory / f"{DEFAULT_DIAGNOSED_ACTIVATION}.jsonl").stat().st_mode
    assert stat.S_IMODE(file_mode) == 0o600


async def test_a_directory_found_wider_is_narrowed_before_a_write(tmp_path: Path) -> None:
    """A directory someone else made readable is made the owner's again (§2:3)."""
    directory = tmp_path / "diagnostics"
    directory.mkdir()
    directory.chmod(0o755)

    await FileDiagnosticRecord(directory=directory, file_bytes=_BOUND).write(diagnostic_entry())

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


async def test_a_file_stops_at_its_bound_with_one_truncation_marker(tmp_path: Path) -> None:
    """§6:3: an entry past the bound is not written; one last line marks the file."""
    record = FileDiagnosticRecord(directory=tmp_path / "diagnostics", file_bytes=MIN_FILE_BYTES)
    path = tmp_path / "diagnostics" / f"{DEFAULT_DIAGNOSED_ACTIVATION}.jsonl"
    chunk = "x" * 500

    with structlog.testing.capture_logs() as captured:
        for number in range(20):
            await record.write(diagnostic_entry(body={"n": number, "text": chunk}))

    assert path.stat().st_size <= MIN_FILE_BYTES
    lines = _lines(path)
    assert lines[-1] == {
        "activation_id": DEFAULT_DIAGNOSED_ACTIVATION,
        "truncated": True,
        "truncated_at": "2026-10-13T12:00:00.000000+00:00",
    }
    assert all("truncated" not in one for one in lines[:-1])
    kept = len(lines) - 1
    assert [one["body"]["n"] for one in lines[:-1]] == list(range(kept))
    assert len([one for one in captured if one["event"] == DIAGNOSTIC_NOT_WRITTEN]) == 20 - kept
    assert chunk not in repr(captured)


async def test_nothing_more_is_written_once_a_file_is_marked(tmp_path: Path) -> None:
    """A small entry after the marker does not land after it (§6:3)."""
    record = FileDiagnosticRecord(directory=tmp_path / "diagnostics", file_bytes=MIN_FILE_BYTES)
    path = tmp_path / "diagnostics" / f"{DEFAULT_DIAGNOSED_ACTIVATION}.jsonl"
    await record.write(diagnostic_entry(body={"text": "x" * (MIN_FILE_BYTES * 2)}))
    marked = path.read_bytes()

    await record.write(diagnostic_entry(body={"n": 1}))

    assert path.read_bytes() == marked
    assert _lines(path) == [_lines(path)[-1]]


async def test_another_activations_file_is_not_touched_by_a_truncation(tmp_path: Path) -> None:
    """The bound is per file: one runaway activation stops itself and nothing else."""
    record = FileDiagnosticRecord(directory=tmp_path / "diagnostics", file_bytes=MIN_FILE_BYTES)
    await record.write(diagnostic_entry(body={"text": "x" * (MIN_FILE_BYTES * 2)}))
    other = "9a1c7e52-6b3d-4f80-8e2a-1c5d7b9f0e46"

    await record.write(diagnostic_entry(other, body={"n": 1}))

    assert len(_entries(tmp_path / "diagnostics", other)) == 1


@pytest.mark.parametrize("bound", [MIN_FILE_BYTES - 1, 0])
def test_a_bound_too_small_for_a_marker_is_refused(tmp_path: Path, bound: int) -> None:
    """Below the minimum, the marker could not fit and the bound could not hold."""
    with pytest.raises(ValueError, match="at least"):
        FileDiagnosticRecord(directory=tmp_path, file_bytes=bound)


def test_a_bound_that_is_not_an_exact_int_is_refused(tmp_path: Path) -> None:
    """A ``bool`` is not a byte count."""
    with pytest.raises(TypeError):
        FileDiagnosticRecord(directory=tmp_path, file_bytes=True)


async def test_the_sweep_leaves_a_subdirectory_and_reads_no_entry(tmp_path: Path) -> None:
    """§7:2: files by their last write, nothing else; a file's contents are not read."""
    directory = tmp_path / "diagnostics"
    record = FileDiagnosticRecord(directory=directory, file_bytes=_BOUND)
    await record.write(diagnostic_entry())
    (directory / "nested").mkdir()
    path = directory / f"{DEFAULT_DIAGNOSED_ACTIVATION}.jsonl"
    old = (DEFAULT_RECORDED_AT - timedelta(days=40)).timestamp()
    os.utime(path, (old, old))
    path.chmod(0o200)  # write-only: a sweep that read the file would fail here

    deleted = await record.purge_before(DEFAULT_RECORDED_AT - timedelta(days=30))

    assert deleted == 1
    assert [one.name for one in directory.iterdir()] == ["nested"]


async def test_a_swept_activation_may_be_written_again(tmp_path: Path) -> None:
    """A truncated file swept away no longer bars its name."""
    directory = tmp_path / "diagnostics"
    record = FileDiagnosticRecord(directory=directory, file_bytes=MIN_FILE_BYTES)
    await record.write(diagnostic_entry(body={"text": "x" * (MIN_FILE_BYTES * 2)}))
    await record.purge_before(DEFAULT_RECORDED_AT.replace(year=2100))

    await record.write(diagnostic_entry(body={"n": 1}))

    assert len(_entries(directory, DEFAULT_DIAGNOSED_ACTIVATION)) == 1


def _torn(monkeypatch: pytest.MonkeyPatch, *, after: int) -> None:
    """Make the next append write ``after`` bytes and then find the disk full."""
    original = store_module._write
    state = {"armed": True}

    def write(descriptor: int, data: memoryview) -> int:
        if not state["armed"]:
            return original(descriptor, data)
        state["armed"] = False
        original(descriptor, data[:after])
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(store_module, "_write", write)


async def test_an_append_that_fails_part_way_is_cut_back_and_the_next_line_lands_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§6:2: each line lands whole; a torn one never joins the next."""
    record = FileDiagnosticRecord(directory=tmp_path / "diagnostics", file_bytes=_BOUND)
    await record.write(diagnostic_entry(body={"n": 1}))
    path = tmp_path / "diagnostics" / f"{DEFAULT_DIAGNOSED_ACTIVATION}.jsonl"
    before = path.read_bytes()
    _torn(monkeypatch, after=7)

    with structlog.testing.capture_logs() as captured:
        await record.write(diagnostic_entry(body={"n": 2}))
    assert path.read_bytes() == before
    await record.write(diagnostic_entry(body={"n": 3}))

    assert [one["body"]["n"] for one in _lines(path)] == [1, 3]
    assert [one["event"] for one in captured] == [DIAGNOSTIC_NOT_WRITTEN]


async def test_a_truncation_marker_that_fails_part_way_is_cut_back_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = FileDiagnosticRecord(directory=tmp_path / "diagnostics", file_bytes=MIN_FILE_BYTES)
    await record.write(diagnostic_entry(body={"n": 1}))
    path = tmp_path / "diagnostics" / f"{DEFAULT_DIAGNOSED_ACTIVATION}.jsonl"
    before = path.read_bytes()
    _torn(monkeypatch, after=5)

    await record.write(diagnostic_entry(body={"text": "x" * MIN_FILE_BYTES}))

    assert path.read_bytes() == before


async def test_a_symbolic_link_in_the_directorys_place_is_neither_written_nor_swept(
    tmp_path: Path,
) -> None:
    """§2:3, §7:2: the record's files are reached through the directory it verified."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    bystander = elsewhere / "keep.txt"
    bystander.write_text("not the record's", encoding="utf-8")
    old = (DEFAULT_RECORDED_AT - timedelta(days=400)).timestamp()
    os.utime(bystander, (old, old))
    directory = tmp_path / "diagnostics"
    directory.symlink_to(elsewhere, target_is_directory=True)
    record = FileDiagnosticRecord(directory=directory, file_bytes=_BOUND)

    await record.write(diagnostic_entry())
    with pytest.raises(DiagnosticRecordError):
        await record.purge_before(DEFAULT_RECORDED_AT)

    assert sorted(one.name for one in elsewhere.iterdir()) == ["keep.txt"]


def _uncuttable(monkeypatch: pytest.MonkeyPatch, *, times: int) -> None:
    """Make the next ``times`` cuts fail as the storage does."""
    original = store_module._truncate
    left = {"n": times}

    def truncate(descriptor: int, size: int) -> None:
        if left["n"] > 0:
            left["n"] -= 1
            raise OSError(5, "Input/output error")
        original(descriptor, size)

    monkeypatch.setattr(store_module, "_truncate", truncate)


async def test_a_torn_tail_whose_cut_failed_is_cut_before_the_next_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§6:2: where the rollback fails too, nothing joins the torn line once storage recovers."""
    record = FileDiagnosticRecord(directory=tmp_path / "diagnostics", file_bytes=_BOUND)
    await record.write(diagnostic_entry(body={"n": 1}))
    path = tmp_path / "diagnostics" / f"{DEFAULT_DIAGNOSED_ACTIVATION}.jsonl"
    _torn(monkeypatch, after=9)
    _uncuttable(monkeypatch, times=1)

    await record.write(diagnostic_entry(body={"n": 2}))
    await record.write(diagnostic_entry(body={"n": 3}))

    assert [one["body"]["n"] for one in _lines(path)] == [1, 3]


async def test_a_torn_tail_that_still_cannot_be_cut_takes_no_further_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = FileDiagnosticRecord(directory=tmp_path / "diagnostics", file_bytes=_BOUND)
    await record.write(diagnostic_entry(body={"n": 1}))
    path = tmp_path / "diagnostics" / f"{DEFAULT_DIAGNOSED_ACTIVATION}.jsonl"
    _torn(monkeypatch, after=9)
    _uncuttable(monkeypatch, times=2)

    await record.write(diagnostic_entry(body={"n": 2}))
    torn = path.read_bytes()
    with structlog.testing.capture_logs() as captured:
        await record.write(diagnostic_entry(body={"n": 3}))

    assert path.read_bytes() == torn
    assert [one["event"] for one in captured] == [DIAGNOSTIC_NOT_WRITTEN]
    await record.write(diagnostic_entry(body={"n": 4}))
    assert [one["body"]["n"] for one in _lines(path)] == [1, 4]


def _open_descriptors() -> int:
    return len(list(Path("/proc/self/fd").iterdir()))


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="needs /proc to count descriptors")
async def test_a_directory_that_cannot_be_narrowed_leaks_no_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write that fails at the directory still closes what it opened (§2:4)."""
    directory = tmp_path / "diagnostics"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    record = FileDiagnosticRecord(directory=directory, file_bytes=_BOUND)

    def refuse(descriptor: int, mode: int) -> None:
        del descriptor, mode
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "fchmod", refuse)
    before = _open_descriptors()

    for _ in range(5):
        await record.write(diagnostic_entry())

    assert _open_descriptors() == before


# --- ADR-0333 §3: the observer's file beside the activation's ---------------------


def _observed(activation_id: str = DEFAULT_DIAGNOSED_ACTIVATION, **body: object) -> DiagnosticEntry:
    """An entry the observer writes about ``activation_id``."""
    return diagnostic_entry(
        activation_id,
        source=DiagnosticSource.OBSERVER,
        kind=DiagnosticKind.STEP,
        body={"stage": "end", **body},
    )


async def test_an_observer_entry_goes_to_its_own_file_and_never_the_activations(
    tmp_path: Path,
) -> None:
    """§3:1: ``<id>.observer.jsonl``; nothing the observer writes reaches ``<id>.jsonl``."""
    directory = tmp_path / "diagnostics"
    record = FileDiagnosticRecord(directory=directory, file_bytes=_BOUND)
    own = diagnostic_entry(body={"n": 1})

    await record.write(own)
    await record.write(_observed(n=2))
    await record.write(diagnostic_entry(kind=DiagnosticKind.RETURNED, body={"n": 3}))

    assert OBSERVER_SUFFIX == ".observer.jsonl"
    assert sorted(one.name for one in directory.iterdir()) == [
        f"{DEFAULT_DIAGNOSED_ACTIVATION}.jsonl",
        f"{DEFAULT_DIAGNOSED_ACTIVATION}.observer.jsonl",
    ]
    assert [one.body["n"] for one in _entries(directory, DEFAULT_DIAGNOSED_ACTIVATION)] == [1, 3]
    observed = _lines(directory / f"{DEFAULT_DIAGNOSED_ACTIVATION}{OBSERVER_SUFFIX}")
    assert [(one["source"], one["body"]["n"]) for one in observed] == [("observer", 2)]
    assert [list(one) for one in observed] == [
        ["activation_id", "source", "kind", "recorded_at", "body"]
    ]


async def test_the_observer_file_is_the_owners_alone(tmp_path: Path) -> None:
    """§3:2, ADR-0314 §2:3: ``0600`` whatever the umask, as the activation's own file."""
    previous = os.umask(0)
    try:
        record = FileDiagnosticRecord(directory=tmp_path / "diagnostics", file_bytes=_BOUND)
        await record.write(_observed())
    finally:
        os.umask(previous)

    path = tmp_path / "diagnostics" / f"{DEFAULT_DIAGNOSED_ACTIVATION}{OBSERVER_SUFFIX}"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


async def test_each_of_an_activations_two_files_has_its_own_bound_and_marker(
    tmp_path: Path,
) -> None:
    """§3:2: the observer's file stops at its bound alone, and the activation's goes on."""
    directory = tmp_path / "diagnostics"
    record = FileDiagnosticRecord(directory=directory, file_bytes=MIN_FILE_BYTES)
    observed = directory / f"{DEFAULT_DIAGNOSED_ACTIVATION}{OBSERVER_SUFFIX}"

    await record.write(_observed(text="x" * (MIN_FILE_BYTES * 2)))
    await record.write(_observed(n=1))
    await record.write(diagnostic_entry(body={"n": 2}))

    assert observed.stat().st_size <= MIN_FILE_BYTES
    assert _lines(observed) == [
        {
            "activation_id": DEFAULT_DIAGNOSED_ACTIVATION,
            "truncated": True,
            "truncated_at": "2026-10-13T12:00:00.000000+00:00",
        }
    ]
    assert [one.body for one in _entries(directory, DEFAULT_DIAGNOSED_ACTIVATION)] == [{"n": 2}]


async def test_an_activations_marked_file_bars_no_observer_entry(tmp_path: Path) -> None:
    """§3:2: an activation's own file at its bound still leaves room for what was learned."""
    directory = tmp_path / "diagnostics"
    record = FileDiagnosticRecord(directory=directory, file_bytes=MIN_FILE_BYTES)
    await record.write(diagnostic_entry(body={"text": "x" * (MIN_FILE_BYTES * 2)}))

    await record.write(_observed(n=1))

    observed = _lines(directory / f"{DEFAULT_DIAGNOSED_ACTIVATION}{OBSERVER_SUFFIX}")
    assert [one["body"]["n"] for one in observed] == [1]


@pytest.mark.parametrize("stale", [SUFFIX, OBSERVER_SUFFIX])
async def test_each_file_is_swept_by_its_own_last_write(tmp_path: Path, stale: str) -> None:
    """§3:2, ADR-0314 §7:2: either file may outlive the other; each ages from its own write."""
    directory = tmp_path / "diagnostics"
    record = FileDiagnosticRecord(directory=directory, file_bytes=_BOUND)
    await record.write(diagnostic_entry())
    await record.write(_observed())
    old = (DEFAULT_RECORDED_AT - timedelta(days=40)).timestamp()
    os.utime(directory / f"{DEFAULT_DIAGNOSED_ACTIVATION}{stale}", (old, old))

    deleted = await record.purge_before(DEFAULT_RECORDED_AT - timedelta(days=30))

    assert deleted == 1
    kept = OBSERVER_SUFFIX if stale == SUFFIX else SUFFIX
    assert [one.name for one in directory.iterdir()] == [f"{DEFAULT_DIAGNOSED_ACTIVATION}{kept}"]


async def test_an_id_too_long_for_the_observer_file_is_refused_for_it_alone(
    tmp_path: Path,
) -> None:
    """§6:1 over the second name: the bound on a name holds for the longer suffix too."""
    directory = tmp_path / "diagnostics"
    record = FileDiagnosticRecord(directory=directory, file_bytes=_BOUND)
    long_id = "e" * (255 - len(SUFFIX))

    with structlog.testing.capture_logs() as captured:
        await record.write(diagnostic_entry(long_id))
        await record.write(_observed(long_id))

    assert [one.name for one in directory.iterdir()] == [f"{long_id}{SUFFIX}"]
    assert [one["source"] for one in captured if one["event"] == DIAGNOSTIC_NOT_WRITTEN] == [
        "observer"
    ]
    assert plain_file_name(long_id)
    assert not plain_file_name(long_id, DiagnosticSource.OBSERVER)


# --- ADR-0337 §8:12-§8:13: the follow-up file beside the activation's -------------


def _followed_up(
    activation_id: str = DEFAULT_DIAGNOSED_ACTIVATION, **body: object
) -> DiagnosticEntry:
    """An entry the follow-up asker writes about a call of ``activation_id``."""
    return diagnostic_entry(
        activation_id,
        source=DiagnosticSource.FOLLOW_UP,
        kind=DiagnosticKind.RETURNED,
        body={"answer": "a guess", **body},
    )


async def test_a_follow_up_entry_goes_to_its_own_file_and_never_the_others(
    tmp_path: Path,
) -> None:
    """§8:12: ``<id>.followup.jsonl``; nothing the asker writes reaches either other file."""
    directory = tmp_path / "diagnostics"
    record = FileDiagnosticRecord(directory=directory, file_bytes=_BOUND)

    await record.write(diagnostic_entry(body={"n": 1}))
    await record.write(_observed(n=2))
    await record.write(_followed_up(n=3))

    assert FOLLOW_UP_SUFFIX == ".followup.jsonl"
    assert sorted(one.name for one in directory.iterdir()) == [
        f"{DEFAULT_DIAGNOSED_ACTIVATION}.followup.jsonl",
        f"{DEFAULT_DIAGNOSED_ACTIVATION}.jsonl",
        f"{DEFAULT_DIAGNOSED_ACTIVATION}.observer.jsonl",
    ]
    assert [one.body["n"] for one in _entries(directory, DEFAULT_DIAGNOSED_ACTIVATION)] == [1]
    observed = _lines(directory / f"{DEFAULT_DIAGNOSED_ACTIVATION}{OBSERVER_SUFFIX}")
    assert [one["body"]["n"] for one in observed] == [2]
    followed = _lines(directory / f"{DEFAULT_DIAGNOSED_ACTIVATION}{FOLLOW_UP_SUFFIX}")
    assert [(one["source"], one["kind"], one["body"]["n"]) for one in followed] == [
        ("follow_up", "returned", 3)
    ]


async def test_the_follow_up_file_is_the_owners_alone(tmp_path: Path) -> None:
    """§8:13, ADR-0314 §2:3: ``0600`` whatever the umask, as every file of the record."""
    previous = os.umask(0)
    try:
        record = FileDiagnosticRecord(directory=tmp_path / "diagnostics", file_bytes=_BOUND)
        await record.write(_followed_up())
    finally:
        os.umask(previous)

    path = tmp_path / "diagnostics" / f"{DEFAULT_DIAGNOSED_ACTIVATION}{FOLLOW_UP_SUFFIX}"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


async def test_the_follow_up_file_has_its_own_bound_and_marker(tmp_path: Path) -> None:
    """§8:13, ADR-0314 §6:3: the follow-up file stops at its bound alone."""
    directory = tmp_path / "diagnostics"
    record = FileDiagnosticRecord(directory=directory, file_bytes=MIN_FILE_BYTES)
    followed = directory / f"{DEFAULT_DIAGNOSED_ACTIVATION}{FOLLOW_UP_SUFFIX}"

    await record.write(_followed_up(text="x" * (MIN_FILE_BYTES * 2)))
    await record.write(_followed_up(n=1))
    await record.write(diagnostic_entry(body={"n": 2}))

    assert followed.stat().st_size <= MIN_FILE_BYTES
    assert _lines(followed) == [
        {
            "activation_id": DEFAULT_DIAGNOSED_ACTIVATION,
            "truncated": True,
            "truncated_at": "2026-10-13T12:00:00.000000+00:00",
        }
    ]
    assert [one.body for one in _entries(directory, DEFAULT_DIAGNOSED_ACTIVATION)] == [{"n": 2}]


@pytest.mark.parametrize("stale", [SUFFIX, FOLLOW_UP_SUFFIX])
async def test_the_follow_up_file_is_swept_by_its_own_last_write(
    tmp_path: Path, stale: str
) -> None:
    """§8:13, ADR-0314 §7:2: the follow-up file ages from its own write, not the activation's."""
    directory = tmp_path / "diagnostics"
    record = FileDiagnosticRecord(directory=directory, file_bytes=_BOUND)
    await record.write(diagnostic_entry())
    await record.write(_followed_up())
    old = (DEFAULT_RECORDED_AT - timedelta(days=40)).timestamp()
    os.utime(directory / f"{DEFAULT_DIAGNOSED_ACTIVATION}{stale}", (old, old))

    deleted = await record.purge_before(DEFAULT_RECORDED_AT - timedelta(days=30))

    assert deleted == 1
    kept = FOLLOW_UP_SUFFIX if stale == SUFFIX else SUFFIX
    assert [one.name for one in directory.iterdir()] == [f"{DEFAULT_DIAGNOSED_ACTIVATION}{kept}"]


@pytest.mark.parametrize("source", list(DiagnosticSource))
async def test_an_id_ending_followup_names_no_file_of_any_source(
    tmp_path: Path, source: DiagnosticSource
) -> None:
    """§8:12: an id ending ``.followup`` would name its own file like a follow-up file."""
    directory = tmp_path / "diagnostics"
    record = FileDiagnosticRecord(directory=directory, file_bytes=_BOUND)

    with structlog.testing.capture_logs() as captured:
        await record.write(diagnostic_entry("x.followup", source=source))

    assert not directory.exists() or list(directory.iterdir()) == []
    dropped = [one for one in captured if one["event"] == DIAGNOSTIC_NOT_WRITTEN]
    assert [(one["activation_id"], one["source"]) for one in dropped] == [
        ("unreadable", source.value)
    ]


async def test_an_id_too_long_for_the_follow_up_file_is_refused_for_it_alone(
    tmp_path: Path,
) -> None:
    """§6:1 over the third name: the bound on a name holds for the follow-up's suffix too."""
    directory = tmp_path / "diagnostics"
    record = FileDiagnosticRecord(directory=directory, file_bytes=_BOUND)
    long_id = "e" * (255 - len(SUFFIX))

    with structlog.testing.capture_logs() as captured:
        await record.write(diagnostic_entry(long_id))
        await record.write(_followed_up(long_id))

    assert [one.name for one in directory.iterdir()] == [f"{long_id}{SUFFIX}"]
    assert [one["source"] for one in captured if one["event"] == DIAGNOSTIC_NOT_WRITTEN] == [
        "follow_up"
    ]
