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

**Through the directory it verified.** The directory is opened once per operation,
refusing a symbolic link in its place, and every file is reached relative to that
descriptor: a name swapped for a link between a check and a use cannot send a write, or
the sweep's deletions, anywhere else.

**A line lands whole or not at all** (§6:2). An append that fails part-way — a full
disk — is cut back to the length the file had before it, so the next line never joins
a torn one. Where even the cut fails, the length is remembered, and no later line is
appended to that file until the cut has been made.

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
#: The directory itself, opened for its listing and as the anchor of every file
#: operation; never a symbolic link in its place.
_DIRECTORY_FLAGS: Final = os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

#: The one write every append goes through, named so a test can make it fail part-way.
_write: Callable[[int, memoryview], int] = os.write

#: The one cut every rollback goes through, named so a test can make it fail too.
_truncate: Callable[[int, int], None] = os.ftruncate

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
        # The files left with a torn tail a rollback could not cut, by the length of
        # their last whole line: cut before anything more is appended to them (§6:2).
        self._torn: dict[str, int] = {}

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
        directory = self._opened_directory(create=True)
        try:
            descriptor = os.open(name, _OPEN_FLAGS, _FILE_MODE, dir_fd=directory)
            try:
                os.fchmod(descriptor, _FILE_MODE)
                self._mend(name, descriptor)
                size = os.fstat(descriptor).st_size
                try:
                    if size + len(line) + len(marker) <= self._file_bytes:
                        _append_whole(descriptor, line, size)
                        return
                    if size + len(marker) <= self._file_bytes:
                        _append_whole(descriptor, marker, size)
                except _TornError as torn:
                    self._torn[name] = torn.size
                    raise
                self._truncated.add(name)
            finally:
                os.close(descriptor)
        finally:
            os.close(directory)
        msg = "the entry would take the activation's file past its bound, which is now marked"
        raise DiagnosticRecordError(msg)

    def _mend(self, name: str, descriptor: int) -> None:
        """Cut a torn tail an earlier failed rollback left, before anything is appended.

        Raises:
            OSError: If the cut fails again; the file stays torn and nothing is appended.
        """
        size = self._torn.get(name)
        if size is None:
            return
        _truncate(descriptor, size)
        del self._torn[name]

    def _opened_directory(self, *, create: bool) -> int:
        """The record's directory, opened, verified a directory and owner-only (§2:3).

        Args:
            create: Create it ``0700`` where it is missing, and narrow it where it is
                found wider, as a write does; a sweep does neither.

        Returns:
            A descriptor on it, which the caller closes.

        Raises:
            FileNotFoundError: If it is missing and ``create`` is not set.
            DiagnosticRecordError: If its name is taken by a symbolic link or by
                anything not a directory.
        """
        if create:
            with contextlib.suppress(FileExistsError):
                self._directory.mkdir(mode=_DIRECTORY_MODE)
        try:
            descriptor = os.open(self._directory, _DIRECTORY_FLAGS)
        except FileNotFoundError:
            raise
        except OSError as exc:
            msg = "the diagnostic record's directory is a symbolic link or not a directory"
            raise DiagnosticRecordError(msg) from exc
        try:
            if create and stat.S_IMODE(os.fstat(descriptor).st_mode) != _DIRECTORY_MODE:
                os.fchmod(descriptor, _DIRECTORY_MODE)
        except BaseException:
            # Not yet the caller's to close, so closed here on every way out.
            os.close(descriptor)
            raise
        return descriptor

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
        """Unlink each regular file last written before ``horizon_ns``; count them.

        Every name is taken relative to the verified directory, and a symbolic link in
        the directory's place refuses the sweep rather than sweeping where it points.
        """
        try:
            directory = self._opened_directory(create=False)
        except FileNotFoundError:
            return 0
        try:
            return self._swept(directory, horizon_ns)
        finally:
            os.close(directory)

    def _swept(self, directory: int, horizon_ns: int) -> int:
        try:
            with os.scandir(directory) as listing:
                names = [one.name for one in listing]
        except OSError as exc:
            msg = "the diagnostic record's directory could not be listed"
            raise DiagnosticRecordError(msg) from exc
        deleted = 0
        for name in names:
            try:
                status = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if not stat.S_ISREG(status.st_mode) or status.st_mtime_ns >= horizon_ns:
                    continue
                os.unlink(name, dir_fd=directory)
            except FileNotFoundError:
                continue
            except OSError as exc:
                msg = "a file in the diagnostic record could not be deleted"
                raise DiagnosticRecordError(msg) from exc
            self._truncated.discard(name)
            self._torn.pop(name, None)
            deleted += 1
        return deleted


class _RefusedIdError(DiagnosticRecordError):
    """An activation id that is not a plain file name (§6:1)."""


class _TornError(OSError):
    """An append failed part-way and its rollback failed too, leaving ``size`` to cut to."""

    def __init__(self, size: int) -> None:
        super().__init__("an append failed part-way and could not be cut back")
        self.size = size


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


def _append_whole(descriptor: int, data: bytes, size: int) -> None:
    """Append all of ``data``, or cut the file back to ``size`` and raise (§6:2).

    Raises:
        OSError: If the append failed, once the file is its old length again.
        _TornError: If the append failed and so did the cut, naming the length the
            file must be cut to before anything more is appended.
    """
    try:
        _write_all(descriptor, data)
    except OSError as failed:
        try:
            _truncate(descriptor, size)
        except OSError as uncut:
            raise _TornError(size) from uncut
        raise failed from None


def _write_all(descriptor: int, data: bytes) -> None:
    """Write all of ``data`` at the file's end, as one append where the system allows."""
    view = memoryview(data)
    while view:
        written = _write(descriptor, view)
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
