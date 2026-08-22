#!/usr/bin/env python3
"""Mirror the documented untracked per-clone files into the sibling clones.

One agent per clone (ADR-0015 §2), and each clone carries local state that no
merge ever moves between them: ``.env``, ``.mcp.json``, whatever the next tool
needs. Drift is discovered the expensive way — a dispatched lane reports a tool
absent or a setting unset, halfway through its work (issue #1390).

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
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

#: The list of per-clone files, relative to this script.
DEFAULT_LIST = Path(__file__).with_name("clone_sync_files.txt")
#: The integration branch a clone must be sitting on to count as free.
FREE_BRANCH = "main"
#: A sibling clone is the source clone's name plus `-<digits>`.
_SIBLING_SUFFIX = re.compile(r"-(\d+)$")
#: What an explicit selector on the command line may be, and nothing else.
_CLONE_NUMBER = re.compile(r"\d+")


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
        SyncError: If a path is tracked in the target, or the destination would
            resolve outside it.
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

    lines: list[str] = []
    for relative in synced:
        src = source / relative
        dst = target / relative
        if not src.is_file():
            lines.append(f"  skip {relative}: absent in {source}")
            continue
        if dst.is_file() and dst.read_bytes() == src.read_bytes():
            lines.append(f"  same {relative}")
            continue
        verb = "would copy" if dry_run else "copied"
        lines.append(f"  {verb} {relative}")
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            _replace_atomically(src, dst)
    return lines


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
    for target in targets:
        clone = inspect(target, synced)
        if clone.reason is not None:
            named = bool(args.numbers)
            print(f"{target}: SKIPPED — {clone.reason}", file=sys.stderr if named else sys.stdout)
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
