"""Fresh-state memory format boundary for ADR-0275 §12.

Advanced by ADRs 0276, 0280, 0281, 0283, 0284 and 0286.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Final

from ai_assistant.core.errors import IncompatibleStateError, MemoryStoreError

#: The episode-record format this build writes and the only one it serves. ADR-0275
#: §12 minted the marker at 1 for the M36 record; ADR-0276 §7 advances it to 2 for the
#: schema_version-2 record, so a store written before that tree is refused before
#: mutation exactly as a pre-M36 store is, its files neither erased nor upgraded; ADR-0280
#: §7 advances it to 3 for the schema_version-3 record, and ADR-0281 §6 to 4 for the
#: schema_version-4 record, on the same terms. ADR-0283 §12 advances it to 5 for the
#: numbered, channel-indexed memory store and ``ActivationLinks.parks``, in the memory
#: store and the conversation store alike, again with no migration or version-4 read.
#: ADR-0284 §9 advances it to 6 for the schema_version-5 record, which loses
#: ``response_kind``, ``model_eligible``, the trigger's ``conversation`` and the episode's
#: ``disposition``, and requires ``origin`` and a resume's stages — with no migration or
#: earlier read path, so the hub moves to a fresh data directory. ADR-0286 §13 advances it
#: to 7 for the schema_version-6 record, which may be open, and for the memory store's
#: indexed open column, on the same terms.
EPISODE_RECORD_FORMAT: Final[int] = 7


def check_format(conn: sqlite3.Connection, *, allow_empty: bool = False) -> bool:
    """Refuse pre-M39 state before mutation; return whether the current marker exists."""
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not tables and allow_empty:
            return False
        if "episode_record_format" in tables:
            rows = conn.execute("SELECT version FROM episode_record_format").fetchall()
            if rows == [(EPISODE_RECORD_FORMAT,)]:
                return True
    except sqlite3.Error as exc:
        msg = "cannot read episode record format"
        raise MemoryStoreError(msg) from exc
    raise IncompatibleStateError(
        "memory store requires a fresh M39 data directory",
        expected=f"episode record format {EPISODE_RECORD_FORMAT}",
        found="missing or unsupported episode record format",
        operator_action=("Stop the old hub and configure a new empty development data directory."),
    )


def inspect_existing(path: str) -> None:
    """Check existing files without allowing SQLite recovery to modify them.

    A read-only connection suffices for a clean rollback-mode database. Pending
    journals and WAL state are recovered only in an owner-only temporary copy;
    SQLite must not touch the rejected original or its shared-memory sidecar.
    The normal writable opener rechecks the marker inside its initialization
    transaction after this probe has admitted the recovered format.

    The marker is the whole test, for the conversation store as for the memory
    store: the conversation store's turn table and its column check are retired
    (ADR-0283 §6, §12), so there is no second shape to probe.
    """
    if path == ":memory:":
        return
    try:
        source = Path(path)
        if not source.exists():
            return
        source = source.resolve()
        sidecars = tuple(Path(f"{source}{suffix}") for suffix in ("-journal", "-wal", "-shm"))
        if _wal_header(source) or any(file.exists() or file.is_symlink() for file in sidecars):
            _inspect_copy(source, sidecars)
        else:
            with contextlib.closing(
                sqlite3.connect(
                    f"{source.resolve().as_uri()}?mode=ro", uri=True, isolation_level=None
                )
            ) as conn:
                _inspect_connection(conn)
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise MemoryStoreError("cannot inspect existing episode record format") from exc


def _wal_header(path: Path) -> bool:
    # A closed WAL database can have no sidecars. Even mode=ro may create them
    # on its next read, so route that header through the private copy as well.
    with path.open("rb") as stream:
        header = stream.read(20)
    return header.startswith(b"SQLite format 3\0") and b"\x02" in header[18:20]


def _inspect_connection(conn: sqlite3.Connection) -> None:
    check_format(conn, allow_empty=True)


def _file_state(path: Path) -> tuple[int, int, int, int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _inspect_copy(source: Path, sidecars: tuple[Path, ...]) -> None:
    files = (source, *sidecars)
    before = tuple(_file_state(file) for file in files)
    with tempfile.TemporaryDirectory(prefix="assistant-format-") as directory:
        copied = Path(directory) / source.name
        for file, state in zip(files, before, strict=True):
            if state is None or (file.is_symlink() and file != source):
                continue
            target = Path(directory) / file.name
            target.touch(mode=0o600, exist_ok=False)
            with file.open("rb") as reader, target.open("wb") as writer:
                shutil.copyfileobj(reader, writer)
        if before != tuple(_file_state(file) for file in files):
            raise MemoryStoreError("store changed during format inspection; retry opening it")
        journal = Path(f"{copied}-journal")
        if journal.exists():
            _refuse_super_journal(journal)
        with contextlib.closing(sqlite3.connect(copied, isolation_level=None)) as conn:
            _inspect_connection(conn)


def _refuse_super_journal(journal: Path) -> None:
    # A multi-database transaction can name a super-journal outside the copied
    # directory. Never let recovery of a probe follow and delete that original.
    # These stores do not use ATTACH; leave such external recovery to its owner.
    with journal.open("rb") as stream:
        trailer_size = 16
        if stream.seek(0, os.SEEK_END) < trailer_size:
            return
        stream.seek(-trailer_size, os.SEEK_END)
        trailer = stream.read(trailer_size)
    if trailer[-8:] == bytes.fromhex("d9d505f920a163d7") and int.from_bytes(trailer[:4], "big"):
        raise MemoryStoreError("format inspection requires recovery of a multi-database journal")
