"""The diagnostic record: one file per activation, written and never read (ADR-0314).

The store implementing both of ADR-0314 §8's Protocols:
:class:`~ai_assistant.core.protocols.DiagnosticSink`, which every emitter is handed
where ``Settings.diagnostic_record`` is on, and
:class:`~ai_assistant.core.protocols.DiagnosticRetention`, which the ``Engine``'s
retention sweep is handed whether it is on or off (§7:3). The store itself is handed to
nothing (§3:3).

**Here, in the leaf no subsystem imports** (§3:3). The record holds raw outside text,
planning's thinking and other people's words, and it is safe only because nothing reads
it back (§3:1). A store no subsystem can import cannot be opened inside one, so the
write-only property is ``lint-imports``' to hold, as the trace store's walk is. **This
class has no read**: it appends lines and deletes whole files by age, and it never
opens a file for reading, its own tail included. The owner reads the files with the
server's own tools (§3:4).

**The file** (§6). ``<directory>/<activation_id>.jsonl``, an id that is not a plain
file name refused (§6:1). Each entry is one line holding one JSON object, appended
whole in the order written (§6:2). A file holds at most the composition root's
``DIAGNOSTIC_FILE_BYTES``: an entry that would take it past is not written; one last
line marks the file truncated and when, and nothing more is written to it (§6:3). The
room for that last line is kept free from the start, so the marker never takes the file
past the bound either.

**Owner-only** (§2:3). The directory is created ``0700`` and each file ``0600``, and a
directory found wider is narrowed before a file is written into it.

**A failure to write never propagates** (§2:4): it is logged naming the activation, the
source and the failure's class, and never any content. A cancellation reaching a write
waits for the line to land whole, then is re-raised (§2:5).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import stat
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import structlog
from pydantic import ValidationError

from ai_assistant.core.diagnostics import DIAGNOSTIC_NOT_WRITTEN
from ai_assistant.core.errors import DiagnosticRecordError
from ai_assistant.core.types import DiagnosticEntry, fault_class_of

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import UtcInstant

_log = structlog.get_logger(__name__)

#: Each activation's file's suffix (§6:1).
SUFFIX: Final = ".jsonl"

#: The smallest bound a file may be given: room for a truncation marker and a line.
MIN_FILE_BYTES: Final = 4096

_DIRECTORY_MODE: Final = 0o700
_FILE_MODE: Final = 0o600
_OPEN_FLAGS: Final = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC

#: What a refused or unreadable id is logged as, since it may carry anything.
_UNREADABLE: Final = "unreadable"

#: The longest name a file system takes for one entry.
_NAME_BYTES: Final = 255

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


class FileDiagnosticRecord:
    """The diagnostic record under one directory (ADR-0314 §6, §7).

    Structurally implements :class:`~ai_assistant.core.protocols.DiagnosticSink` and
    :class:`~ai_assistant.core.protocols.DiagnosticRetention`. Nothing is opened at
    construction: the directory is created at the first write, so a deployment with
    the record off never gains one.
    """

    def __init__(self, *, directory: Path, file_bytes: int) -> None:
        """Point the record at its directory, and bound its files.

        Args:
            directory: ``<data_dir>/diagnostics``, as the composition root names it.
            file_bytes: ``DIAGNOSTIC_FILE_BYTES``, the most one file holds (§6:3).

        Raises:
            TypeError: If ``file_bytes`` is not an exact ``int``.
            ValueError: If it is below :data:`MIN_FILE_BYTES`.
        """
        if type(file_bytes) is not int:
            msg = "a diagnostic file's bound must be an integer"
            raise TypeError(msg)
        if file_bytes < MIN_FILE_BYTES:
            msg = f"a diagnostic file's bound must be at least {MIN_FILE_BYTES} bytes"
            raise ValueError(msg)
        self._directory = Path(directory)
        self._file_bytes = file_bytes
        self._lock = asyncio.Lock()
        # The files marked truncated by this process. Nothing is read from disk to
        # learn it: reading a file's tail would be reading an entry back (§3:1).
        self._truncated: set[str] = set()

    @property
    def directory(self) -> Path:
        """Where the record's files are."""
        return self._directory

    # --- the write seam ------------------------------------------------------

    async def write(self, entry: DiagnosticEntry) -> None:
        """Append ``entry`` to its activation's file. No failure escapes (§2:4).

        Args:
            entry: The entry, stamped by its emitter.

        Raises:
            CancelledError: Re-raised once the line has landed whole (§2:5).
        """
        try:
            snapshot = DiagnosticEntry.model_validate(entry.model_dump())
        except ValidationError as exc:
            _dropped(None, None, exc)
            return
        try:
            name = _file_name(snapshot.activation_id)
            line = (snapshot.model_dump_json() + "\n").encode("utf-8")
            marker = _marker(snapshot.activation_id, snapshot.recorded_at)
            async with self._lock:
                await _run_to_completion(self._append_sync, name, line, marker)
        except Exception as exc:  # every failure to write, and nothing that is not one
            refused = isinstance(exc, _RefusedIdError)
            _dropped(None if refused else snapshot.activation_id, snapshot.source.value, exc)

    def _append_sync(self, name: str, line: bytes, marker: bytes) -> None:
        """Append one line, or the truncation marker in its place (§6:2-§6:3).

        Raises:
            DiagnosticRecordError: If the file is already truncated, or this entry
                would take it past its bound: the entry is not written.
            OSError: If the directory or the file cannot be written.
        """
        if name in self._truncated:
            msg = "the activation's file is marked truncated; nothing more is written to it"
            raise DiagnosticRecordError(msg)
        self._prepare_directory()
        descriptor = os.open(self._directory / name, _OPEN_FLAGS, _FILE_MODE)
        try:
            os.fchmod(descriptor, _FILE_MODE)
            size = os.fstat(descriptor).st_size
            if size + len(line) + len(marker) <= self._file_bytes:
                _write_all(descriptor, line)
                return
            if size + len(marker) <= self._file_bytes:
                _write_all(descriptor, marker)
            self._truncated.add(name)
        finally:
            os.close(descriptor)
        msg = "the entry would take the activation's file past its bound, which is now marked"
        raise DiagnosticRecordError(msg)

    def _prepare_directory(self) -> None:
        """Create the directory owner-only, or narrow one found wider (§2:3).

        Raises:
            DiagnosticRecordError: If the name is taken by something not a directory.
        """
        with contextlib.suppress(FileExistsError):
            self._directory.mkdir(mode=_DIRECTORY_MODE)
        found = self._directory.lstat()
        if not stat.S_ISDIR(found.st_mode):
            msg = "the diagnostic record's directory is not a directory"
            raise DiagnosticRecordError(msg)
        if stat.S_IMODE(found.st_mode) != _DIRECTORY_MODE:
            self._directory.chmod(_DIRECTORY_MODE)

    # --- the retention seam ---------------------------------------------------

    async def purge_before(self, instant: UtcInstant) -> int:
        """Delete every file whose last write is older than ``instant`` (§7:2).

        Reads the directory's listing and each file's metadata, and no entry.

        Args:
            instant: The window's edge; a file last written at it or after is kept.

        Returns:
            How many files were deleted.

        Raises:
            DiagnosticRecordError: If the directory cannot be listed or a file in it
                cannot be deleted.
        """
        horizon = (instant - _EPOCH) // timedelta(microseconds=1) * 1000
        async with self._lock:
            return await _run_to_completion(self._purge_sync, horizon)

    def _purge_sync(self, horizon_ns: int) -> int:
        """Unlink each regular file last written before ``horizon_ns``; count them."""
        try:
            with os.scandir(self._directory) as listing:
                entries = list(listing)
        except FileNotFoundError:
            return 0
        except OSError as exc:
            msg = "the diagnostic record's directory could not be listed"
            raise DiagnosticRecordError(msg) from exc
        deleted = 0
        for found in entries:
            try:
                status = found.stat(follow_symlinks=False)
                if not stat.S_ISREG(status.st_mode) or status.st_mtime_ns >= horizon_ns:
                    continue
                Path(found.path).unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                msg = "a file in the diagnostic record could not be deleted"
                raise DiagnosticRecordError(msg) from exc
            self._truncated.discard(found.name)
            deleted += 1
        return deleted


class _RefusedIdError(DiagnosticRecordError):
    """An activation id that is not a plain file name (§6:1)."""


def _file_name(activation_id: str) -> str:
    """The activation's file's name, or a refusal where the id is not a plain file name.

    Raises:
        _RefusedIdError: If the id is empty, ``.`` or ``..``, carries a separator or
            a NUL, or makes a name too long for a file system.
    """
    separators = {os.sep, "\0"} | ({os.altsep} if os.altsep else set())
    name = f"{activation_id}{SUFFIX}"
    if (
        activation_id in {"", ".", ".."}
        or any(one in activation_id for one in separators)
        or len(name.encode("utf-8", errors="replace")) > _NAME_BYTES
    ):
        msg = "an activation id that is not a plain file name names no diagnostic file"
        raise _RefusedIdError(msg)
    return name


def _marker(activation_id: str, at: datetime) -> bytes:
    """The last line of a truncated file: which activation, that it was cut, and when.

    The instant is written at a fixed width, so every marker of one file is one length
    and the room kept for it is exact.
    """
    when = at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")
    line = {"activation_id": activation_id, "truncated": True, "truncated_at": when}
    return (json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8")


def _write_all(descriptor: int, data: bytes) -> None:
    """Write all of ``data`` at the file's end, as one append where the system allows."""
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        view = view[written:]


def _dropped(activation_id: str | None, source: str | None, error: Exception) -> None:
    """Log an entry not written: activation, source and class, never content (§2:4)."""
    _log.warning(
        DIAGNOSTIC_NOT_WRITTEN,
        activation_id=_UNREADABLE if activation_id is None else activation_id,
        source=_UNREADABLE if source is None else source,
        error_class=fault_class_of(error),
    )


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes (ADR-0054).

    The eighth copy of the helper every store carries rather than an import from a
    sibling, for the reason the trace store's copy states: this package is a leaf
    that may import nothing but ``core``. Holding on is what makes a cancelled write
    safe (ADR-0314 §2:5): the lock is not released, and the next line not started,
    while a line is still being appended; the absorbed cancellation is re-raised once
    the worker has finished.

    Args:
        fn: The synchronous work to run.
        *args: Its arguments.

    Returns:
        Whatever ``fn`` returned.

    Raises:
        BaseException: Whatever the worker raised, once it has finished; or the
            absorbed cancellation, which takes precedence.
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


__all__ = ["MIN_FILE_BYTES", "SUFFIX", "FileDiagnosticRecord"]
