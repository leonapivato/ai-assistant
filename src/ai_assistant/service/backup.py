"""``ai-assistant-backup``: the cold data directory, encrypted (ADR-0123).

The fourth member of the offline-tool family, and here for the family's reason
(§10): "Its entry point must take the instance lock; the lock is
``service/lock.py``; ``lint-imports``' 'nothing imports the service' contract
means the entry point has to *be* in ``service/``; and ``service`` may import
``app`` and ``core`` (ADR-0083 §8), which is how the other three reach their
mechanisms."

**What it copies is a directory, not a set of stores** (§1). Every regular file
under ``Settings.data_dir``, at any depth, byte for byte, except the three §3
excludes. It opens no store and carries no list of stores, and that is the point
rather than a simplification: "the count in the most authoritative document about
the data directory is already wrong by two, and nothing detected it. A backup that
carried its own list of stores would have been wrong by two in the same way, and
the symptom would have arrived at a restore."

**What it refuses is most of the decision.** A contended lock; an entry that is
not a regular file, a directory or an excluded name; a SQLite sidecar anywhere in
the directory, before the copy and again after it; any copied file whose
fingerprint moved across the copy; a destination that already exists, before the
copy and again at publication; and a destination inside the directory being
copied. Each is a condition an operator changes and re-runs, which is why they
all exit ``78``.

**And the artifact is proved by restoring it** (§9), into a verification
directory held to §7's staging discipline rather than to a system temporary
directory's — because the check "is the one moment this tool writes a complete
decrypted copy of everything the user has accumulated". A verification that
cannot run safely reports the backup *written but unverified*; a verification that
runs and fails is a failed backup, and the artifact is removed.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import os
import shutil
import stat
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from ai_assistant import __version__
from ai_assistant.app import build_measure_reader
from ai_assistant.core.config import load_settings
from ai_assistant.core.errors import AssistantError, ConfigurationError
from ai_assistant.service import artifact, datadir, passphrase
from ai_assistant.service.agev1 import DEFAULT_WORK_FACTOR
from ai_assistant.service.artifact import SQLITE_MAGIC, Manifest, ManifestEntry
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART, classify
from ai_assistant.service.lock import LOCK_FILENAME, InstanceLock
from ai_assistant.service.refusal import RefusalError
from ai_assistant.wire.address import socket_path

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator, Sequence
    from typing import BinaryIO

    from ai_assistant.core.config import Settings

#: The three suffixes that make a file a SQLite sidecar (ADR-0123 §2, §3).
SIDECAR_SUFFIXES: Final = ("-journal", "-wal", "-shm")

#: Where the file change counter lives in a SQLite database's header: four
#: big-endian bytes at offset 24. §2 asks for it beside the stat fields because
#: "a same-sized write inside one timestamp tick moves none of them".
_CHANGE_COUNTER_OFFSET: Final = 24
_CHANGE_COUNTER_BYTES: Final = 4

#: The verification tree's root name under the system temporary directory, and
#: the mode everything this tool creates there carries (§9).
_VERIFY_ROOT_STEM: Final = "ai-assistant-backup-verify"
_OWNER_ONLY_DIR: Final = 0o700

#: What a filesystem says when it cannot make a hard link at all. §2's
#: publication has to be an operation that "fails when the destination already
#: exists rather than replacing it", and ``link`` is the only such primitive for
#: a file — so where it is unavailable the answer is a refusal naming the remedy,
#: never a ``rename`` that would quietly replace a predecessor.
_NO_HARD_LINKS: Final = frozenset({errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS, errno.EMLINK})

#: How deeply the walk will nest before refusing. One descriptor is held per
#: level and that is not removable — dropping an ancestor's means re-finding it
#: by name, which is the re-resolution the descriptors exist to avoid — so the
#: honest answer is a bound with a diagnostic rather than an ``EMFILE`` or a
#: ``RecursionError`` an operator has to decode. ADR-0083's data directory does
#: not nest at all, so 64 is headroom rather than a constraint.
_MAX_DEPTH: Final = 64

#: How much of the data directory's digest names its verification namespace. §9
#: keys the namespace to the *resolved* source directory so that two deployments
#: sharing a temporary parent cannot sweep each other's live verification tree.
_NAMESPACE_CHARS: Final = 32

_DESCRIPTION = """
Write a complete, encrypted copy of this deployment's data directory to a local
file (ADR-0123).

Run it with the hub stopped: it takes the same instance lock, so it cannot run
beside one. It copies every regular file in the data directory except the trace
store, the instance lock and the socket, encrypts the whole thing to a passphrase
you hold, and then proves the artifact by restoring it into a scratch directory
before it publishes it.

The passphrase is the only key. Nothing on this machine can recover it, which is
the property that makes the artifact worth having: a key kept only on the laptop
being backed up is no key at all on the day that laptop is gone.
"""

_EPILOG = """
examples:
  ai-assistant-backup ~/backups/assistant-2026-08-09.age
  ai-assistant-backup /media/usb/assistant.age --passphrase-file ~/.assistant-backup-pass
"""


@dataclass(frozen=True, slots=True)
class _Fingerprint:
    """What §2 records about a file before the copy and re-reads after it."""

    device: int
    inode: int
    length: int
    mtime_ns: int
    change_counter: int | None


@dataclass(frozen=True, slots=True)
class _Frame:
    """One level of the iterative walk: a held directory and what is left to enter."""

    descriptor: int
    children: list[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class _SourceFile:
    """One copyable file, and the descriptor of the directory holding it.

    The descriptor is valid only while the walk is inside that directory, which
    is the whole point of the shape: it is closed on the way back out.
    """

    relative: str
    name: str
    directory: int


@dataclass(frozen=True, slots=True)
class _Source:
    """The result of the pre-copy scan: what will be copied, and its fingerprints."""

    entries: tuple[ManifestEntry, ...]
    fingerprints: dict[str, _Fingerprint]


def main(argv: Sequence[str] | None = None) -> int:
    """Take a backup and return the process's exit code.

    Args:
        argv: Command-line arguments, for tests. ``None`` reads ``sys.argv``.

    Returns:
        ``0`` when an artifact was published, ``1`` when the lock was held or the
        attempt failed in a way a later one may not, and ``78`` for every refusal
        ADR-0123 defines — each of which is a condition a human changes before the
        same command could succeed. The vocabulary is the hub's
        (:mod:`ai_assistant.service.exits`).
    """
    args = _parse_args(argv)
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        return _report(exc)
    try:
        return _back_up(settings, args)
    except RefusalError as exc:
        print(f"the backup was refused: {exc}", file=sys.stderr)
        return EXIT_DEPLOYMENT
    except KeyboardInterrupt:
        # Nothing is published until the very last step, so an interrupt leaves
        # the destination untouched — the temporary file is removed on the way
        # out by the same `finally` every other failure takes (§2).
        print(
            "\ninterrupted. Nothing was published — run this again when you like.", file=sys.stderr
        )
        return EXIT_RESTART
    except (AssistantError, OSError) as exc:
        return _report(exc)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Read the destination and how the passphrase arrives.

    The data directory is not among them: it comes from configuration
    (``ASSISTANT_DATA_DIR``), for the reason the other offline tools give — a tool
    that could be pointed at a different deployment's store than the hub uses is a
    way to attribute one deployment's state to another.
    """
    parser = argparse.ArgumentParser(
        prog="ai-assistant-backup",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("destination", type=Path, help="where to write the artifact")
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--passphrase-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="read the passphrase from this file's first line, for an unattended run",
    )
    source.add_argument(
        "--generate-passphrase",
        action="store_true",
        help="mint a passphrase, show it once, and use it (ADR-0123 §5)",
    )
    return parser.parse_args(argv)


def _back_up(settings: Settings, args: argparse.Namespace) -> int:
    """Refuse what can be refused cheaply, then take the lock and do the work."""
    data_dir = settings.data_dir
    # The parent is resolved and the leaf is not: §11 asks for "the resolved
    # destination", and the leaf is the one component that must *not* exist.
    named = Path(args.destination)
    parent = named.parent.resolve()
    destination = parent / named.name

    # §11's disclosure, before anything is written anywhere.
    print(f"about to write a complete encrypted copy of {data_dir}")
    print(f"                                         to {destination}")
    _refuse_destination_inside_source(destination, parent=parent, data_dir=data_dir)
    _refuse_existing(destination)

    # The directory is validated before the passphrase is asked for, so an
    # operator does not type one — twice — only to be told their data directory
    # is unreadable. Everything above this line is cheaper still.
    try:
        datadir.prepare(data_dir)
    except (AssistantError, OSError) as exc:
        return _report(exc)

    secret = passphrase.resolve(
        source=args.passphrase_file, generated=args.generate_passphrase, confirm=True
    )
    if not args.generate_passphrase:
        print(f"note: {passphrase.CUSTODY_REMINDER}", file=sys.stderr)

    lock = InstanceLock(data_dir / LOCK_FILENAME)
    try:
        held = lock.acquire()
    except OSError as exc:
        return _report(exc)
    if not held:
        return _report_contention(lock)
    try:
        return _run_locked(settings, destination=destination, secret=secret)
    finally:
        lock.release()


def _run_locked(settings: Settings, *, destination: Path, secret: str) -> int:
    """Everything that must happen with the instance lock held."""
    data_dir = settings.data_dir
    excluded = _excluded_paths(settings)
    _refuse_sidecars(data_dir)
    source = _scan(data_dir, excluded=excluded)
    manifest = Manifest(
        format_version=artifact.FORMAT_VERSION,
        taken_at=datetime.now(UTC),
        project_version=__version__,
        files=source.entries,
    )
    print(f"copying {len(source.entries)} file(s), {manifest.total_length} bytes")

    temporary = _write_temporary(
        destination, data_dir=data_dir, manifest=manifest, secret=secret, excluded=excluded
    )
    try:
        _refuse_if_source_moved(data_dir, source=source, excluded=excluded)
        verified = _verify(temporary, data_dir=data_dir, secret=secret)
        _publish(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    print(f"wrote {destination} ({destination.stat().st_size} bytes)")
    if verified is not None:
        print(f"warning: the artifact is written but unverified: {verified}", file=sys.stderr)
    else:
        print("verified by restoring it into a scratch directory and checking every file.")
    return EXIT_OK


def _write_temporary(
    destination: Path,
    *,
    data_dir: Path,
    manifest: Manifest,
    secret: str,
    excluded: frozenset[str],
) -> Path:
    """Build the artifact beside its destination, under a name nothing mistakes for one.

    §2 requires the same-directory placement for ADR-0104 §1's reason: an atomic
    publication is atomic "only within one filesystem and same-directory is the
    only placement that guarantees it without probing".
    """
    try:
        handle, name = tempfile.mkstemp(
            dir=destination.parent, prefix=f".{destination.name}.", suffix=".partial"
        )
    except OSError as exc:
        msg = f"the artifact cannot be built beside {destination}: {exc}"
        raise RefusalError(msg) from exc
    temporary = Path(name)
    try:
        with os.fdopen(handle, "wb") as out:
            artifact.write_artifact(
                out,
                sources=_sources(data_dir, excluded=excluded),
                manifest=manifest,
                passphrase=secret,
                work_factor=DEFAULT_WORK_FACTOR,
            )
            out.flush()
            os.fsync(out.fileno())
    except (OSError, tarfile.TarError) as exc:
        temporary.unlink(missing_ok=True)
        msg = f"the artifact could not be written: {exc}"
        raise RefusalError(msg) from exc
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _publish(temporary: Path, destination: Path) -> None:
    """Promote the temporary file, by an operation that cannot replace anything.

    ``link`` rather than ``rename``: §2 requires that "publication is an operation
    that fails when the destination already exists rather than replacing it", and
    a rename replaces. This is ADR-0104 §3's posture at its own seam, with the
    same primitive available.
    """
    try:
        os.link(temporary, destination)
    except FileExistsError as exc:
        msg = (
            f"{destination} came into existence while the artifact was being written, so "
            f"it was not published — publishing would have destroyed whatever is there now"
        )
        raise RefusalError(msg) from exc
    except OSError as exc:
        if exc.errno in _NO_HARD_LINKS:
            # A filesystem with no hard links — FAT on a USB stick is the one an
            # operator will actually meet, and §11's own example destination is
            # `/media/usb/...`. There is no other non-replacing primitive to fall
            # back to, and §2 forbids falling back to one that replaces, so this
            # is a refusal with the remedy rather than a quiet `rename`.
            msg = (
                f"{destination} is on a filesystem that does not support the hard link this "
                f"tool publishes by ({exc.strerror}), and the only alternative would be an "
                f"operation that can overwrite an existing backup; write the artifact to a "
                f"local filesystem and copy it there yourself"
            )
            raise RefusalError(msg) from exc
        msg = f"the artifact could not be published to {destination}: {exc}"
        raise RefusalError(msg) from exc
    temporary.unlink(missing_ok=True)


def _refuse_existing(destination: Path) -> None:
    """The fast refusal (§2): it costs nothing and happens before the store is read."""
    if destination.exists() or destination.is_symlink():
        msg = (
            f"{destination} already exists; this tool never writes over a backup, so choose "
            f"another name or move that one aside"
        )
        raise RefusalError(msg)


def _refuse_destination_inside_source(destination: Path, *, parent: Path, data_dir: Path) -> None:
    """§11's containment test, over resolved paths and before any temporary file.

    Resolved rather than lexical because "a destination named through a symbolic
    link — ``/safe/backup.age`` where ``/safe`` points at the data directory —
    passes any comparison of the strings and lands exactly where the rule exists
    to prevent".
    """
    source = data_dir.resolve()
    if parent.is_relative_to(source):
        msg = (
            f"{destination} would be written inside the data directory it copies "
            f"({parent} is at or beneath {source}); a backup that lives on the disk whose "
            f"loss it exists for is not a backup, and it grows the next one"
        )
        raise RefusalError(msg)


def _excluded_paths(settings: Settings) -> frozenset[str]:
    """Assemble §3's exclusions, each from the module that owns its name.

    The trace store's path comes from the composition root, because that is where
    the store is *created* — ADR-0123 §3's whole argument for not restating any of
    these here. ``service`` reaches it the way ADR-0083 §8 allows and the way the
    other offline tools already do; :func:`~ai_assistant.app.build_measure_reader`
    is the composition root's own statement of where that file is, and reading it
    constructs nothing but a path holder.

    The instance lock's name comes from :mod:`ai_assistant.service.lock` and the
    socket's from :mod:`ai_assistant.wire.address`, because those modules define
    them — restating either at the composition root would rebuild the stale-name
    seam §3 rejects, and ``lint-imports`` would not even allow it.

    **If you are adding a file to the data directory, read this.** ADR-0123 §3
    binds the lane that creates the problem rather than asking this list to
    anticipate it: "A later lane that places in the data directory a file subject
    to a clause forbidding it to leave the device returns to this decision, adds it
    to the exclusions above, and makes its path reachable from the module that owns
    it in the same change. Until it does, this ADR authorises no such file to be
    written there." The clause is repeated here because this is the declaration the
    tool actually reads, and §3 is explicit that a sentence in an ADR nobody
    re-reads while renaming a file is not where the binding takes effect. A lane
    that forgets entirely fails in the safe direction for durability — the file is
    backed up, which costs size — and in the unsafe one for privacy, which is why
    the reminder is here rather than only there.
    """
    data_dir = settings.data_dir
    names = {LOCK_FILENAME, socket_path(data_dir).name}
    trace_store = build_measure_reader(settings).store
    if trace_store.is_relative_to(data_dir):
        names.add(trace_store.relative_to(data_dir).as_posix())
    # A trace store outside the data directory is not in the walk at all, so
    # ADR-0119 §12 is satisfied by the copy rule rather than by this set.
    excluded = set(names)
    for name in names:
        # §3: "Excluding a path also excludes that path's SQLite sidecars … A
        # protected store's sidecars are part of the store and never enter an
        # artifact." Redundant with §2's directory-wide refusal, and kept because
        # the clause it protects is absolute.
        excluded.update(f"{name}{suffix}" for suffix in SIDECAR_SUFFIXES)
    return frozenset(excluded)


def _scan(data_dir: Path, *, excluded: frozenset[str]) -> _Source:
    """Fingerprint and digest every copyable file, in walk order."""
    entries: list[ManifestEntry] = []
    fingerprints: dict[str, _Fingerprint] = {}
    for source in _walk(data_dir, excluded=excluded):
        fingerprint, sha256, length = _measure(data_dir, source)
        fingerprints[source.relative] = fingerprint
        entries.append(ManifestEntry(path=source.relative, length=length, sha256=sha256))
    return _Source(entries=tuple(entries), fingerprints=fingerprints)


def _sources(data_dir: Path, *, excluded: frozenset[str]) -> Iterator[tuple[str, BinaryIO]]:
    """The same walk again, yielding each file open for the copy."""
    for source in _walk(data_dir, excluded=excluded):
        yield (
            source.relative,
            artifact.open_regular_at(
                source.directory, source.name, shown=data_dir / source.relative
            ),
        )


def _walk(data_dir: Path, *, excluded: frozenset[str]) -> Generator[_SourceFile]:
    """Walk the directory depth-first, holding one descriptor per *level*.

    **Descriptors, because a name is not an object** (ADR-0123 §1). A directory
    that was a directory when it was listed can be a symlink by the time a file
    inside it is opened, and every check on the file then passes while the bytes
    come from somewhere else. Each directory is opened ``O_NOFOLLOW`` from its
    parent's descriptor, so the open that matters goes to the directory that was
    verified.

    **Per level rather than per directory**, which is what keeps the cost off the
    tree's *width*: retaining one descriptor for every directory made an ordinary
    wide tree fail with ``EMFILE`` past ``RLIMIT_NOFILE`` and produce no artifact,
    against §1's "at any depth".

    **And per level is where it stops**, deliberately. The remaining cost is one
    descriptor per level of nesting, and it is not removable: dropping an
    ancestor's descriptor means re-finding it by name to reach its later
    children, which is precisely the re-resolution this walk exists to avoid.
    What is done instead is to make the limit legible — the traversal is
    iterative, so depth costs no interpreter stack, and a tree deeper than
    :data:`_MAX_DEPTH` is a refusal that names the number rather than an
    ``EMFILE`` an operator has to decode. Nothing in this system nests the data
    directory at all, so the bound is three orders of magnitude of headroom over
    the shape ADR-0083 actually describes.

    **The copy walks a second time rather than holding the first walk open**, and
    the two walks are reconciled rather than assumed equal: both are sorted and
    deterministic, and :func:`~ai_assistant.service.artifact.write_artifact`
    refuses if the sequence it is offered disagrees with the manifest. A directory
    swapped between the walks is either a symlink — refused here — or a different
    real directory, whose files carry different inodes and are refused by §2's
    after-the-copy fingerprint check.

    Args:
        data_dir: The directory to walk.
        excluded: §3's exclusion set, as data-directory-relative paths.

    Yields:
        Each copyable file, with its directory's descriptor open. Declared a
        generator rather than an iterator because closing it is what releases
        those descriptors when a caller stops early.

    Raises:
        RefusalError: On a symbolic link, an entry of any other kind (§1), or a
            tree deeper than :data:`_MAX_DEPTH`.
    """
    frames: list[_Frame] = []
    try:
        root = artifact.open_directory_at(None, str(data_dir), shown=data_dir)
        files, children = _level(root, "", data_dir=data_dir, excluded=excluded)
        frames.append(_Frame(descriptor=root, children=children))
        yield from files
        while frames:
            frame = frames[-1]
            if not frame.children:
                os.close(frames.pop().descriptor)
                continue
            name, relative = frame.children.pop(0)
            if len(frames) >= _MAX_DEPTH:
                msg = (
                    f"{data_dir / relative} is more than {_MAX_DEPTH} directories deep; this "
                    f"tool holds one descriptor per level and will not walk further, so move "
                    f"whatever nests that far out of the data directory"
                )
                raise RefusalError(msg)
            child = artifact.open_directory_at(frame.descriptor, name, shown=data_dir / relative)
            files, children = _level(child, f"{relative}/", data_dir=data_dir, excluded=excluded)
            frames.append(_Frame(descriptor=child, children=children))
            yield from files
    finally:
        for frame in frames:
            os.close(frame.descriptor)


def _level(
    directory: int, prefix: str, *, data_dir: Path, excluded: frozenset[str]
) -> tuple[list[_SourceFile], list[tuple[str, str]]]:
    """Read one directory: its copyable files, and the subdirectories to descend into.

    The ``scandir`` is drained here rather than iterated across the descent,
    because an open one holds a descriptor of its own — leaving it open would put
    the per-directory cost this walk exists to bound straight back.

    Args:
        directory: The descriptor for the directory to read.
        prefix: Its data-directory-relative path, with a trailing separator.
        data_dir: The data directory, for diagnostics.
        excluded: §3's exclusion set.

    Returns:
        Its files, and its subdirectories as ``(name, relative)`` pairs.

    Raises:
        RefusalError: On a symbolic link or an entry of any other kind (§1).
    """
    with os.scandir(directory) as scan:
        entries = sorted(scan, key=lambda item: item.name)
    files: list[_SourceFile] = []
    children: list[tuple[str, str]] = []
    for entry in entries:
        relative = prefix + entry.name
        if relative in excluded:
            continue
        shown = data_dir / relative
        if entry.is_symlink():
            msg = (
                f"{shown} is a symbolic link; this tool never follows one and never copies "
                f"one, so remove it or move it out of the data directory"
            )
            raise RefusalError(msg)
        if entry.is_dir(follow_symlinks=False):
            children.append((entry.name, relative))
        elif entry.is_file(follow_symlinks=False):
            files.append(_SourceFile(relative=relative, name=entry.name, directory=directory))
        else:
            msg = (
                f"{shown} is neither a regular file nor a directory, so it cannot be copied "
                f"byte for byte; move it out of the data directory"
            )
            raise RefusalError(msg)
    return files, children


def _refuse_sidecars(data_dir: Path) -> None:
    """Refuse any SQLite sidecar anywhere in the directory (§2, widened by §3).

    Directory-wide, and deliberately including one beside a file §3 excludes: a
    ``-wal`` left by a crashed hub "holds committed pages of exactly the records
    ADR-0119 §12 says may not leave the device". §3's exclusion set is deliberately
    *not* consulted: the point of widening the scan was that a sidecar beside an
    excluded file "was outside a refusal phrased over files the tool would copy,
    which left the crashed trace store as the one state that could reach an
    artifact".
    """
    found = sorted(_sidecars(data_dir))
    if not found:
        return
    msg = (
        f"{data_dir / found[0]} is a SQLite sidecar, so a process is writing to that "
        f"database now or died mid-transaction and copying it would yield a torn file"
        f"{'' if len(found) == 1 else f' ({len(found)} sidecars in all)'}. "
        f"Start the hub and stop it cleanly, then run the backup again."
    )
    raise RefusalError(msg)


def _sidecars(data_dir: Path) -> Iterator[str]:
    """Every sidecar-named entry under the directory, at any depth."""
    stack = [(data_dir, "")]
    while stack:
        directory, prefix = stack.pop()
        try:
            scan = list(os.scandir(directory))
        except OSError as exc:
            msg = f"the data directory {directory} could not be listed: {exc}"
            raise RefusalError(msg) from exc
        for entry in scan:
            relative = prefix + entry.name
            if entry.name.endswith(SIDECAR_SUFFIXES):
                yield relative
            elif entry.is_dir(follow_symlinks=False):
                stack.append((Path(entry.path), f"{relative}/"))


def _measure(data_dir: Path, source: _SourceFile) -> tuple[_Fingerprint, str, int]:
    """Fingerprint and digest one file, both against a single open descriptor.

    **One open, not three, and that is the fix for a real hole rather than a
    tidy-up.** Fingerprinting by ``lstat`` and then digesting by a fresh open left
    a window in which a regular file could become a symbolic link: the ``lstat``
    recorded the link, the open followed it, and because the after-fingerprint was
    the link's too, the two agreed and the artifact was published carrying a file
    from outside the data directory.

    Args:
        data_dir: The data directory, for diagnostics only.
        source: The file to measure, with its directory's descriptor open.

    Returns:
        Its fingerprint, its SHA-256 and its byte length.

    Raises:
        RefusalError: If it is a symbolic link or is not a regular file.
    """
    with artifact.open_regular_at(
        source.directory, source.name, shown=data_dir / source.relative
    ) as handle:
        info = os.fstat(handle.fileno())
        counter = _change_counter(handle)
        sha256, length = artifact.digest_and_length_of(handle)
    return (
        _Fingerprint(
            device=info.st_dev,
            inode=info.st_ino,
            length=info.st_size,
            mtime_ns=info.st_mtime_ns,
            change_counter=counter,
        ),
        sha256,
        length,
    )


def _change_counter(handle: BinaryIO) -> int | None:
    """SQLite's file change counter, or ``None`` when the file is not a database.

    §2 reads it beside the stat fields for the reason ADR-0104 gives about its own
    equivalent: the stat fields "are insufficient … a same-sized write inside one
    timestamp tick moves none of them".

    Read through ``pread`` so the descriptor's own offset is left where the caller
    put it — the digest reads the same descriptor from the start straight after.
    """
    header = os.pread(handle.fileno(), _CHANGE_COUNTER_OFFSET + _CHANGE_COUNTER_BYTES, 0)
    if not header.startswith(SQLITE_MAGIC) or len(header) < _CHANGE_COUNTER_OFFSET + 4:
        return None
    return int.from_bytes(header[_CHANGE_COUNTER_OFFSET:], "big")


def _refuse_if_source_moved(data_dir: Path, *, source: _Source, excluded: frozenset[str]) -> None:
    """Re-read every fingerprint and re-scan for sidecars, after the copy (§2).

    Both, because neither sees what the other does. The fingerprints catch a
    write to a file that was copied; the second sidecar scan catches "a
    non-cooperating writer that switches a database to WAL and then commits", which
    "puts that commit in a newly created ``-wal``, leaving the main file's length,
    timestamps and change counter where they were".

    The set is compared as well as the fingerprints: a file that appeared or
    vanished across the copy changes what the artifact is a backup *of*, and the
    per-file comparison alone would not see it.

    This narrows the window and does not close it, and §2 does not claim it does.
    """
    seen: set[str] = set()
    for found in _walk(data_dir, excluded=excluded):
        before = source.fingerprints.get(found.relative)
        if before is None:
            msg = (
                f"{data_dir / found.relative} appeared while the backup was being written, "
                f"so the artifact is not a copy of this directory; run the backup again"
            )
            raise RefusalError(msg)
        seen.add(found.relative)
        try:
            after, _sha256, _length = _measure(data_dir, found)
        except OSError as exc:
            msg = f"{data_dir / found.relative} could not be re-read after the copy: {exc}"
            raise RefusalError(msg) from exc
        if after != before:
            msg = (
                f"{data_dir / found.relative} changed while the backup was being written, so "
                f"the copy of it may be torn; stop whatever is writing to the data directory "
                f"and run the backup again"
            )
            raise RefusalError(msg)
    missing = sorted(set(source.fingerprints) - seen)
    if missing:
        msg = (
            f"{data_dir / missing[0]} vanished while the backup was being written, so the "
            f"artifact is not a copy of this directory; run the backup again"
        )
        raise RefusalError(msg)
    _refuse_sidecars(data_dir)


def _verify(temporary: Path, *, data_dir: Path, secret: str) -> str | None:
    """Prove the artifact by restoring it (§9), before it is published.

    Returns:
        ``None`` when the artifact verified, or the reason it could not be
        verified — which §9 routes to "written but unverified" rather than to a
        failure, because "an artifact nobody could check is worth keeping, and one
        that was checked and did not pass is not".

    Raises:
        RefusalError: If the verification ran and the artifact failed it. The caller
            removes the artifact on that path.
    """
    namespace = _verification_namespace(data_dir)
    if namespace is None:
        return "no owner-only scratch directory was available for the check"
    staging = namespace / "store"
    try:
        staging.mkdir(mode=_OWNER_ONLY_DIR)
        manifest = artifact.materialise(temporary, passphrase=secret, staging=staging)
        artifact.verify_materialised(staging, manifest)
    except OSError as exc:
        return f"the check could not be run: {exc}"
    finally:
        # §9's guarantee, stated at the size a process can keep: every path out of
        # this run that the process can act on. A `SIGKILL` is outside it, which is
        # why the namespace is swept by the next run instead.
        shutil.rmtree(namespace, ignore_errors=True)
    return None


def _verification_namespace(data_dir: Path) -> Path | None:
    """Make this source's verification directory, sweeping whatever a dead run left.

    §9 requires the location to be "created with owner-only permissions under a
    parent writable only by its owner", and requires the sweep to be namespaced —
    "an operator with a second data directory, or a test installation beside a
    real one, can have both running at once under the same user and the same
    verification parent", and an unnamespaced sweep would delete a live one.

    The sweep is safe because the caller holds *this* source's instance lock, so
    within this namespace there is no other live run and anything found was left
    by a run that is gone.

    Returns:
        An empty, owner-only directory, or ``None`` when no such location can be
        established — which §9 routes to written-but-unverified.
    """
    namespace = _namespace_for(data_dir)
    try:
        root = namespace.parent
        root.mkdir(mode=_OWNER_ONLY_DIR, exist_ok=True)
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
            return None
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return None
        shutil.rmtree(namespace, ignore_errors=True)
        namespace.mkdir(mode=_OWNER_ONLY_DIR)
    except OSError:
        return None
    return namespace


def _namespace_for(data_dir: Path) -> Path:
    """Where this source's verification tree lives, without creating anything.

    Separate from :func:`_verification_namespace` because that one sweeps, and a
    caller — or a test — that wants to know whether an earlier run left something
    behind must be able to ask without destroying the answer.

    §9 keys the namespace to the **resolved** source directory "for the reason
    §11's containment check is resolved — two spellings of one directory would
    otherwise be two namespaces, and the sweep would never reach half of what it
    is for".

    Args:
        data_dir: The source directory whose backup is being verified.

    Returns:
        The namespace directory's path.
    """
    root = Path(tempfile.gettempdir()) / f"{_VERIFY_ROOT_STEM}-{os.geteuid()}"
    digest = hashlib.sha256(str(data_dir.resolve()).encode("utf-8")).hexdigest()
    return root / digest[:_NAMESPACE_CHARS]


def _report_contention(lock: InstanceLock) -> int:
    """Say that something else holds the lock, hedging the pid exactly as ADR-0083 §1 does."""
    pid = lock.recorded_pid()
    hint = f" (the lock file records pid {pid}, which may be stale)" if pid is not None else ""
    print(
        f"{lock.path} is held by another instance{hint}. Stop the hub, then run this again.",
        file=sys.stderr,
    )
    return EXIT_RESTART


def _report(exc: BaseException) -> int:
    """Print a failure and return the code ADR-0083 §5's test gives it."""
    code, action = classify(exc)
    print(f"the backup did not run: {exc}", file=sys.stderr)
    if action:
        print(f"what to do: {action}", file=sys.stderr)
    return code
