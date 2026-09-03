#!/usr/bin/env python3
"""Mirror the documented untracked per-clone files into the sibling clones.

One agent per clone (ADR-0015 §2), and each clone carries local state that no
merge ever moves between them: ``.env``, whatever the next tool needs. Drift is
discovered the expensive way — a dispatched lane reports a tool absent or a
setting unset, halfway through its work (issue #1390).

The list is data, not code: ``scripts/clone_sync_files.txt``, one
repository-relative path per line, with its own note on why nothing in it is
committed. ``--list`` points at a different one.

Two refusals, and they are the whole safety story:

* **A clone that is not on ``main`` and clean is skipped**, which is the dispatch
  skill's freshness test (§1). Uncommitted work in a clone sitting on ``main`` is
  someone's in-progress change, and a clone on a branch is holding a lane. The
  files being synced are excluded from the cleanliness test — they are exactly
  what is expected to differ.
* **A path git *tracks* in the target is never overwritten**, and that is an
  error rather than a skip: it means the list names a file that has since become
  part of the repository, and copying over it would silently corrupt a checkout.

A clone named explicitly on the command line but not free fails the run; one
merely *found* by the default scan is reported and skipped, because a busy clone
is the ordinary state of a batch mid-flight.

Both refusals are decided **under an exclusive lock on the target**, and the
freshness test is taken again under that lock immediately before the first byte
is written (issue #1409). Deciding and then copying is a window: two syncs from
different source clones could each read one target as free and interleave, leaving
it with ``.env`` from one and ``.mcp.json`` from the other, and a person can start
working in a target after it was found free.

**The lock closes the first and the re-test only narrows the second**, which this
says plainly rather than implying more. Every sync takes the lock, so no sync can
interleave with another. Nobody else takes it — a person working in a target holds
nothing — so every check made before a write is check-then-act against them, and
the residual window is the copy itself. What the re-test buys is that a target
somebody has *already* taken is not written to at all. What it cannot buy is
safety against someone who arrives mid-copy: only a protocol every writer observed
would, and there is none.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

#: The list of per-clone files, relative to this script.
DEFAULT_LIST = Path(__file__).with_name("clone_sync_files.txt")
#: The integration branch a clone must be sitting on to count as free.
FREE_BRANCH = "main"
#: A sibling clone is the source clone's name plus `-<digits>`.
_SIBLING_SUFFIX = re.compile(r"-(\d+)$")
#: What an explicit selector on the command line may be, and nothing else.
_CLONE_NUMBER = re.compile(r"\d+")
#: The per-target lock file, in the target's git directory rather than its work
#: tree: a lock file beside the code would be untracked, and the *next* run's
#: cleanliness test would read the target as dirty because of it.
LOCK_NAME = "clone-sync.lock"
#: How much of two files is compared at a time when deciding whether to copy.
_COMPARE_CHUNK = 1 << 16


class SyncError(Exception):
    """The sync could not proceed."""


class Clone(NamedTuple):
    """A sibling clone and why it is or is not eligible.

    Attributes:
        path: The clone's root.
        reason: Why it was refused, or ``None`` when it is free.
    """

    path: Path
    reason: str | None


def read_list(path: Path) -> list[str]:
    """Read the documented per-clone file list.

    Args:
        path: The list file.

    Returns:
        The repository-relative paths, in file order, without comments or blanks.

    Raises:
        SyncError: If the file cannot be read, or names an absolute or escaping path.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SyncError(f"cannot read the file list {path}: {exc}") from exc
    entries: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        candidate = Path(line)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise SyncError(f"{path}: {line!r} is not a path inside a clone")
        entries.append(line)
    return entries


def _git(*args: str, cwd: Path) -> str:
    """Run git in ``cwd`` and return its stdout.

    Args:
        *args: The git arguments.
        cwd: The directory to run in.

    Returns:
        Standard output, stripped of the trailing newline only.

    Raises:
        SyncError: If git is missing or exits non-zero.
    """
    binary = shutil.which("git")
    if binary is None:
        raise SyncError("git not found on PATH")
    completed = subprocess.run(  # noqa: S603  # fixed argv, no shell, resolved binary
        [binary, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SyncError(f"git {' '.join(args)} in {cwd} failed: {completed.stderr.strip()}")
    return completed.stdout.rstrip("\n")


def dirty_paths(clone: Path, ignoring: Iterable[str]) -> list[str]:
    """Return the working-tree entries that make a clone dirty.

    Args:
        clone: The clone's root.
        ignoring: Paths excluded from the test — the files being synced.

    Returns:
        The porcelain lines that count as dirt. A line this cannot parse is
        *kept*, so an exotic path (a rename, a quoted name) reads as dirty rather
        than as clean — the fail-closed direction, since the cost of a wrong
        "clean" is overwriting someone's work.
    """
    excluded = set(ignoring)
    dirt: list[str] = []
    for line in _git("status", "--porcelain", cwd=clone).splitlines():
        if not line:
            continue
        # Porcelain v1 is "XY " then the path. A line too short to carry one is
        # kept, like any other line this cannot read: unparseable means dirty.
        path = line[3:] if len(line) > 3 else ""  # noqa: PLR2004  # "XY " is three bytes
        if path not in excluded:
            dirt.append(line)
    return dirt


def is_tracked(clone: Path, relative: str) -> bool:
    """Report whether git tracks ``relative`` in ``clone``.

    Args:
        clone: The clone's root.
        relative: The repository-relative path.

    Returns:
        True when the path is in the index.
    """
    return bool(_git("ls-files", "--", relative, cwd=clone))


def inspect(clone: Path, synced: Sequence[str]) -> Clone:
    """Decide whether a clone is free to receive the sync.

    Args:
        clone: The clone's root.
        synced: The paths being synced, excluded from the cleanliness test.

    Returns:
        The clone, carrying its refusal reason where it has one.
    """
    if not (clone / ".git").exists():
        return Clone(clone, "not a git clone")
    try:
        branch = _git("branch", "--show-current", cwd=clone)
        dirt = dirty_paths(clone, synced)
    except SyncError as exc:
        return Clone(clone, str(exc))
    if branch != FREE_BRANCH:
        return Clone(clone, f"on {branch or '(detached HEAD)'}, not {FREE_BRANCH}")
    if dirt:
        return Clone(clone, f"{len(dirt)} uncommitted change(s), e.g. {dirt[0]!r}")
    return Clone(clone, None)


def _git_dir(clone: Path) -> Path | None:
    """Return the directory git keeps ``clone``'s state in.

    Args:
        clone: The clone's root.

    Returns:
        ``.git`` for an ordinary clone, the linked directory it names for a
        worktree, or ``None`` when there is no ``.git`` at all.
    """
    marker = clone / ".git"
    if marker.is_dir():
        return marker
    if not marker.exists():
        return None
    # A linked worktree keeps `.git` as a *file* naming the real directory. Asked
    # rather than parsed — and asked only here, because `git rev-parse` run in a
    # directory that is not a clone walks up and answers about an enclosing one.
    try:
        return Path(_git("rev-parse", "--absolute-git-dir", cwd=clone))
    except SyncError:
        return None


def _acquire(fd: int, target: Path) -> None:
    """Take the exclusive lock on ``fd``, saying so first if it has to wait.

    Args:
        fd: The open lock file.
        target: The clone it guards, for the message.

    Raises:
        SyncError: If the lock cannot be taken at all — a filesystem that does
            not support locking, say. Every other failure in this script is a
            refusal carrying its reason, and a traceback here would be the one
            exception.
    """
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # Say so before blocking. The wait is another sync holding this one
            # target and is bounded by it, but a silent pause reads as a hang.
            # On stderr: stdout carries the report, and this is not part of it.
            print(f"{target}: waiting for another clone-sync to finish here...", file=sys.stderr)
            fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError as exc:
        raise SyncError(f"{target}: cannot take the sync lock: {exc}") from exc


@contextlib.contextmanager
def _target_lock(target: Path) -> Iterator[None]:
    """Hold an exclusive lock on ``target`` for the block.

    Everything decided about a clone — its branch, its dirt, what git tracks in
    it — is read before anything is written, so two syncs from different source
    clones could each read one target as free and then interleave their files
    (issue #1409). The lock makes deciding and copying one turn per target.

    ``fcntl`` rather than a dependency, the way ``service/lock.py`` and the
    embedding-artifact cache already take a lock. The kernel drops it when the
    descriptor closes, so a sync killed mid-copy releases it rather than leaving
    the next one waiting on a lock nobody holds.

    Args:
        target: The clone being copied into.

    Yields:
        Nothing; the lock is held for the duration of the block.
    """
    directory = _git_dir(target)
    if directory is None:
        # Not a clone: `inspect` refuses it, nothing is ever written to it, and
        # there is nowhere outside its work tree to put a lock file anyway.
        yield
        return
    lock = directory / LOCK_NAME
    try:
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    except OSError as exc:
        raise SyncError(f"{target}: cannot open the sync lock {lock}: {exc}") from exc
    try:
        _acquire(fd, target)
        yield
    finally:
        os.close(fd)


def sibling_root(source: Path) -> tuple[Path, str]:
    """Return the directory siblings live in and the name they share.

    The source clone's own name may already carry a ``-N`` suffix, so it is
    stripped: running this from ``ai-assistant-4`` finds the same set as running
    it from ``ai-assistant``.

    Args:
        source: The clone being copied from.

    Returns:
        The parent directory and the base clone name.
    """
    base = _SIBLING_SUFFIX.sub("", source.name)
    return source.parent, base


def find_siblings(source: Path, numbers: Sequence[str]) -> list[Path]:
    """Return the sibling clones to sync into.

    Args:
        source: The clone being copied from.
        numbers: Explicit clone numbers; empty means every sibling on disk.

    Returns:
        The sibling roots, sorted, never including ``source`` itself.
    """
    parent, base = sibling_root(source)
    if numbers:
        # Constrained to digits, and then re-checked after resolution. A selector
        # is pasted straight into a path, and `<base>-../../elsewhere` resolves
        # clean out of the sibling root — which would copy credentials into any
        # unrelated checkout that happens to be on `main` and clean.
        for n in numbers:
            if not _CLONE_NUMBER.fullmatch(n):
                raise SyncError(f"{n!r} is not a clone number; give digits, e.g. `2 3`")
        candidates = [parent / f"{base}-{n}" for n in numbers]
        root = parent.resolve()
        for candidate in candidates:
            if candidate.resolve().parent != root:
                raise SyncError(f"{candidate} is not a sibling of {source}")
    else:
        candidates = [
            path
            for path in parent.glob(f"{base}-*")
            if path.is_dir() and _SIBLING_SUFFIX.search(path.name)
        ]
    return sorted({path.resolve() for path in candidates} - {source.resolve()})


def _refuse_to_escape(target: Path, relative: str) -> None:
    """Refuse a destination that would be written outside the target clone.

    ``is_tracked`` guards a *checked-in* file, and everything on the list is by
    definition ignored — so it says nothing about an ignored **symlink** sitting
    at one of these paths. ``shutil.copy2`` follows a symlink and writes through
    it, so an ignored ``.env -> /etc/somewhere`` in a clone would let a sync
    overwrite a file the sync has no business touching. The same goes for a
    symlinked ancestor directory, which is why the resolved parent is checked and
    not only the leaf.

    Args:
        target: The clone being copied into.
        relative: The repository-relative path.

    Raises:
        SyncError: If the leaf is a symlink, or the destination resolves outside
            ``target``.
    """
    destination = target / relative
    if destination.is_symlink():
        raise SyncError(
            f"{target}: {relative} is a symlink, and copying would write through it\n"
            f"to {destination.resolve(strict=False)}. Remove it, or drop the path from the list."
        )
    root = target.resolve(strict=False)
    parent = destination.parent.resolve(strict=False)
    if parent != root and not parent.is_relative_to(root):
        raise SyncError(
            f"{target}: {relative} resolves to {parent}, outside the clone.\n"
            f"Refusing to write there."
        )


def copy_into(source: Path, target: Path, synced: Sequence[str], *, dry_run: bool) -> list[str]:
    """Copy the listed files from ``source`` into ``target``.

    Args:
        source: The clone being copied from.
        target: The clone being copied into.
        synced: The repository-relative paths.
        dry_run: When set, decide everything and write nothing.

    Returns:
        One report line per path considered.

    Raises:
        SyncError: If a path is tracked in the target, the destination would
            resolve outside it, or the target stopped being free while the
            refusals were being decided.
    """
    # EVERY refusal is decided before the first byte is written. Checking as it
    # copies would leave a target half-synced when a later path is refused — the
    # per-clone configuration then disagrees with both the primary and itself,
    # which is the drift this recipe exists to remove.
    for relative in synced:
        if not (source / relative).is_file():
            continue
        if is_tracked(target, relative):
            raise SyncError(
                f"{target}: git tracks {relative}, so the sync would overwrite a\n"
                f"checked-in file. Remove it from the list — nothing in the list is committed."
            )
        _refuse_to_escape(target, relative)

    # The freshness test again, at the last moment before the first byte. The
    # lock keeps another sync out, but nobody else takes it: a person or an agent
    # can start working in a target between the moment it was found free and now
    # (issue #1409). This *narrows* that window and cannot close it — a check made
    # before a write is check-then-act against a writer holding no lock, so
    # someone arriving during the copy below is not caught, and the module
    # docstring says so. A dry run writes nothing, so it has nothing to guard —
    # the plan it prints is the one `inspect` decided a moment ago, under the
    # same lock.
    if not dry_run:
        busy = inspect(target, synced)
        if busy.reason is not None:
            raise SyncError(
                f"{target}: stopped being free while the sync was deciding — "
                f"{busy.reason}.\nNothing was copied."
            )

    lines: list[str] = []
    for relative in synced:
        src = source / relative
        dst = target / relative
        if not src.is_file():
            lines.append(f"  skip {relative}: absent in {source}")
            continue
        if _has_same_bytes(src, dst):
            lines.append(f"  same {relative}")
            continue
        verb = "would copy" if dry_run else "copied"
        lines.append(f"  {verb} {relative}")
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            _replace_atomically(src, dst)
    return lines


def _has_same_bytes(src: Path, dst: Path) -> bool:
    """Report whether ``dst`` already holds exactly the bytes in ``src``.

    Size first, then a chunked comparison that stops at the first difference —
    rather than ``read_bytes()`` on both, which loads two whole files into memory
    to conclude that nothing needs doing (issue #1409). The list is *documented*
    to hold small per-clone configuration, but nothing enforces that, and this is
    a skip optimisation: its worst case should not exceed the copy it avoids.

    Args:
        src: The file being copied from.
        dst: Where it would go.

    Returns:
        True when ``dst`` is a regular file of the same size and the same content.
    """
    if not dst.is_file():
        return False
    if src.stat().st_size != dst.stat().st_size:
        return False
    with src.open("rb") as left, dst.open("rb") as right:
        while True:
            here, there = left.read(_COMPARE_CHUNK), right.read(_COMPARE_CHUNK)
            if here != there:
                return False
            if not here:
                return True


def _replace_atomically(src: Path, dst: Path) -> None:
    """Copy ``src`` over ``dst`` without ever leaving a partial file in place.

    ``shutil.copy2`` straight onto the destination truncates it and then writes,
    so anything reading that file meanwhile — an agent already running in the
    target clone — can read a half-written ``.env``. Writing beside it and
    renaming means the destination is only ever the old file or the new one.

    Args:
        src: The file to copy.
        dst: Where it goes.
    """
    # `mkstemp`, not a name composed from the destination: a predictable one can
    # be pre-created as a symlink, and copying *to* it would follow the link and
    # write outside the clone — reintroducing, one step later, exactly what
    # `_refuse_to_escape` stops at the destination. `mkstemp` opens with
    # O_CREAT|O_EXCL at mode 0600, so the file this writes is one it created.
    handle, name = tempfile.mkstemp(dir=dst.parent, prefix=f".{dst.name}.", suffix=".clone-sync")
    temporary = Path(name)
    try:
        # Streamed rather than read whole: `copy2` streamed, and a list entry is
        # only a config file by convention — nothing stops one naming something
        # large, and reading it into memory to write it straight back out is a
        # cost with no purchase.
        with src.open("rb") as source_file, os.fdopen(handle, "wb") as sink:
            shutil.copyfileobj(source_file, sink)
        # `copy2`'s other half: mkstemp's 0600 is not the mode the file should
        # land with, and the modification time is worth carrying over too.
        shutil.copystat(src, temporary)
        # Replaces the destination *entry*, so a symlink that appeared there
        # since the preflight is replaced rather than written through.
        temporary.replace(dst)
    finally:
        temporary.unlink(missing_ok=True)


def _sync(args: argparse.Namespace) -> int:
    """Run the sync.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit status.

    Raises:
        SyncError: If the source is not a clone, or a target is tracked-file blocked.
    """
    source = Path(args.source).resolve()
    if not (source / ".git").exists():
        raise SyncError(f"{source} is not a git clone; pass --from <primary clone>")
    synced = read_list(Path(args.list))
    targets = find_siblings(source, args.numbers)
    if not targets:
        print(f"clone-sync: no sibling clones beside {source}")
        return 0

    status = 0
    named = bool(args.numbers)
    for target in targets:
        # Held across deciding *and* copying: a decision made outside it would be
        # about a target another sync could then take (issue #1409).
        with _target_lock(target):
            clone = inspect(target, synced)
            if clone.reason is not None:
                stream = sys.stderr if named else sys.stdout
                print(f"{target}: SKIPPED — {clone.reason}", file=stream)
                if named:
                    status = 1
                continue
            print(f"{target}:")
            for line in copy_into(source, target, synced, dry_run=args.dry_run):
                print(line)
    return status


def _parser() -> argparse.ArgumentParser:
    """Return the CLI parser.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        description="Mirror the documented untracked per-clone files into siblings (issue #1390)."
    )
    parser.add_argument(
        "numbers", nargs="*", help="clone numbers to sync (default: every sibling found)"
    )
    parser.add_argument("--from", dest="source", default=".", help="the clone to copy from")
    parser.add_argument("--list", default=str(DEFAULT_LIST), help="the per-clone file list")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, copy nothing")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        The process exit status: 0, or 1 with the reason on stderr.
    """
    args = _parser().parse_args(argv)
    try:
        return _sync(args)
    except SyncError as exc:
        print(f"clone-sync: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
