#!/usr/bin/env python3
"""Produce and recognise the ratification flip, and guard the ready boundary.

ADR-0165 exempts exactly one commit shape from a fresh review round: **one ADR
file, one changed line, ``- Status: Proposed`` becoming ``- Status: Accepted``,
and nothing else at all** — the ``- Date:`` line included. Everything larger — a
ratification note, the amendment records an ADR schedules for its own
ratification, a second ADR, a typo fix riding along — falls outside it and costs
its round exactly as before. That is the fail-closed direction and it is the
whole design (ADR-0165 §6): the exempted commit is unreviewed by construction, so
everything a reviewer would have caught in it has to be excluded by the shape.

Three commands, and the first two are deliberately the same code:

``ratify``
    Makes the flip commit. Refuses on a dirty tree, on ``main``, on a detached
    ``HEAD``, and on an ADR whose header does not carry exactly one
    ``- Status: Proposed`` line. It verifies its own commit with ``check-shape``
    before returning, because a flip the exemption does not recognise is worse
    than no exemption — it costs a round *and* reads as a bug in ``ship``.

``check-shape``
    Answers "is this commit a ratification flip?" for ``scripts/ship.sh``, which
    re-anchors ADR-0027 §2's acceptance loop onto the parent when it is
    (ADR-0165 §3). The answer is a **reconstruction**: the parent's blob goes
    through the same :func:`render_ratified` that *produced* the child, and the
    result is compared byte for byte. It is never a pattern matched against the
    diff. ADR-0165 §2 requires that, and issue #751 is why — a hand-built replica
    of ``ship.sh``'s floor test reported "clear" for a base move that breached
    the floor, twice, because the replica and the rule had drifted apart. One
    transform, used to produce and to recognise, cannot drift from itself.

``check-ready``
    ADR-0165 §5's guard on the documented finishing recipe: refuse to flip a PR
    out of draft while any ADR the PR adds or modifies still reads ``Proposed``.
    Issue #1044 is two lanes in two days that shipped ready with the flip never
    made, and nothing mechanical caught either.

Everything is stdlib and every git call is a fixed argv, so ``ship.sh`` can run
this with a bare ``python3`` — no environment, no import of the package.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# --------------------------------------------------------------------------- #
# The shape, spelled once                                                      #
# --------------------------------------------------------------------------- #

_STATUS_PROPOSED = "- Status: Proposed"
_STATUS_ACCEPTED = "- Status: Accepted"

_ADR_DIR = "docs/adr"
# A numbered ADR document, which is every ADR and not `template.md`. The four
# digits are ADR-0001's form, restated in ADR-0165 §2's predicate; issue #1244
# tracks what happens to that form past ADR-9999.
_ADR_PATH_RE = re.compile(r"^docs/adr/(\d{4})-.+\.md$")

# `git diff-tree --raw` renders a modification as
# `:<srcmode> <dstmode> <srcsha> <dstsha> M`. Anything else — an add, a delete,
# a rename, a copy, a type change — is a different letter, and a mode change
# keeps the letter while moving a field, so both are read rather than one.
_RAW_FIELDS = 5


class ShapeError(Exception):
    """The input is not in the shape this module requires.

    Every refusal here raises one, so a caller distinguishes "not a ratification
    flip" from "this script broke" by exception type rather than by reading a
    message.
    """


def header_end(lines: Sequence[str]) -> int:
    """Return the index of the first line after an ADR's header block.

    ADR-0165 §2 defines the header as the lines preceding the file's first line
    beginning ``## ``, which is ``## Context`` in every ADR the corpus holds.
    ``Status`` is looked for *inside* those bounds, so a quoted
    ``- Status: Proposed`` in the body — ADRs quote each other's header lines
    constantly, and ADR-0070 §4 carries one at the start of a line — is neither
    counted nor rewritten.

    Args:
        lines: The document's lines, without terminators.

    Returns:
        The index of the first ``## `` line, or ``len(lines)`` if there is none.
    """
    for index, line in enumerate(lines):
        if line.startswith("## "):
            return index
    return len(lines)


def _sole_index(lines: Sequence[str], end: int, matches: Callable[[str], bool], what: str) -> int:
    """Return the one header line index satisfying ``matches``.

    Args:
        lines: The document's lines.
        end: The exclusive end of the header block.
        matches: The test a line must satisfy.
        what: What to call it in the error message.

    Returns:
        The index.

    Raises:
        ShapeError: If the header carries other than exactly one such line.
    """
    found = [i for i in range(end) if matches(lines[i])]
    if len(found) != 1:
        raise ShapeError(f"the header carries {len(found)} {what} lines, expected exactly 1")
    return found[0]


def render_ratified(text: str) -> str:
    """Return ``text`` as it stands once ratified: one line changed, nothing else.

    This is the whole of the flip commit's content change and the only definition
    of it — the header's one ``- Status: Proposed`` line becomes
    ``- Status: Accepted``. The ``- Date:`` line is **not** touched: ADR-0165 §2
    excluded it because a date-shaped second line is a value an unreviewed commit
    chooses, and binding it to the commit's author date does not repair that
    (``git commit --date=…`` and ``GIT_AUTHOR_DATE`` both set it, so the trusted
    source is the same hand writing the line). An author who does need to restamp
    the date writes it in the flip commit and pays the round.

    The match on ``- Status: Proposed`` is **exact string equality**, not a
    prefix, and that is a hardening bought in review rather than a style choice.
    ``Proposed`` is a bare token (ADR-0070 §4), so a line that merely *starts*
    with it carries something more — a caveat, a condition, a note to the merger
    — and rewriting the whole line would silently delete exactly the text most
    likely to say "not yet", while the reconstruction below still agreed.

    Args:
        text: The ``Proposed`` ADR's content.

    Returns:
        The ratified content.

    Raises:
        ShapeError: If the header does not carry exactly one ``- Status: Proposed``
            line.
    """
    lines = text.split("\n")
    status_at = _sole_index(
        lines, header_end(lines), lambda line: line == _STATUS_PROPOSED, repr(_STATUS_PROPOSED)
    )
    lines[status_at] = _STATUS_ACCEPTED
    return "\n".join(lines)


def adr_number(path: str) -> int:
    """Return the ADR number a repository-relative path carries.

    Args:
        path: A repository-relative path.

    Returns:
        The four-digit number.

    Raises:
        ShapeError: If ``path`` is not a numbered ADR document.
    """
    match = _ADR_PATH_RE.match(path)
    if match is None:
        raise ShapeError(f"not a numbered ADR under {_ADR_DIR}/: {path!r}")
    return int(match.group(1))


# --------------------------------------------------------------------------- #
# git                                                                          #
# --------------------------------------------------------------------------- #


def _git_binary() -> str:
    """Return git's absolute path.

    Returns:
        The resolved path.

    Raises:
        ShapeError: If git is not on PATH.
    """
    found = shutil.which("git")
    if found is None:
        raise ShapeError("git not found on PATH")
    return found


def _run_git(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
    """Run git in ``cwd`` without checking its status.

    Args:
        args: The git arguments.
        cwd: The directory to run in.

    Returns:
        The completed process, output uninterpreted.
    """
    return subprocess.run(  # noqa: S603  # fixed argv, no shell, resolved binary
        [_git_binary(), *args],
        cwd=str(cwd),
        capture_output=True,
        check=False,
    )


def _git(*args: str, cwd: Path) -> str:
    """Run git in ``cwd`` and return its stdout.

    Args:
        *args: The git arguments.
        cwd: The directory to run in.

    Returns:
        Standard output, decoded as UTF-8.

    Raises:
        ShapeError: If git fails, or its output is not UTF-8.
    """
    completed = _run_git(args, cwd)
    if completed.returncode != 0:
        raise ShapeError(
            "git " + " ".join(args) + ": " + completed.stderr.decode("utf-8", "replace").strip()
        )
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        # A blob that is not UTF-8 is not an ADR, and refusing here is one of the
        # ways ADR-0165 §2's "not a binary change" clause is met.
        raise ShapeError("git " + " ".join(args) + ": output is not UTF-8") from exc


def repo_root(start: Path) -> Path:
    """Return the work tree root containing ``start``.

    Args:
        start: Any directory inside the work tree.

    Returns:
        The work tree root.
    """
    return Path(_git("rev-parse", "--show-toplevel", cwd=start).strip())


def _blob(root: Path, blob_sha: str) -> str:
    """Return a blob's content by object id.

    Read by object id rather than by ``<rev>:<path>`` so no path resolution,
    attribute or filter can stand between the object the diff named and the bytes
    compared.

    Args:
        root: The work tree root.
        blob_sha: The blob's object id.

    Returns:
        The content, decoded as UTF-8.
    """
    return _git("cat-file", "blob", blob_sha, cwd=root)


def _sole_parent(root: Path, commit: str) -> tuple[str, str]:
    """Return ``(sha, parent)`` for a commit with exactly one parent.

    Args:
        root: The work tree root.
        commit: Any revision.

    Returns:
        The resolved sha and its one parent.

    Raises:
        ShapeError: If the commit does not resolve, or has other than one parent.
    """
    sha = _git("rev-parse", "--verify", commit + "^{commit}", cwd=root).strip()
    parents = _git("rev-list", "--parents", "-n", "1", sha, cwd=root).split()[1:]
    if len(parents) != 1:
        raise ShapeError(f"{sha[:12]} has {len(parents)} parents, expected exactly 1")
    return sha, parents[0]


def _sole_modified_path(root: Path, parent: str, sha: str) -> tuple[str, str, str]:
    """Return ``(path, parent_blob, child_blob)`` for a one-path modification.

    Rename detection is pinned **off** and paths are left unquoted, so the entry
    set is a function of the two commits alone rather than of whatever config the
    caller's clone carries. Off, a rename renders as a delete and an add — two
    entries, which this refuses — where on, it renders as one entry carrying no
    hunks at all. ADR-0165 §2 excludes renames for that reason: a rename's
    identity is a function of its paths, so a byte-identical patch identity can
    cover content nobody saw.

    Args:
        root: The work tree root.
        parent: The parent commit.
        sha: The commit.

    Returns:
        The path, the parent's blob id and the child's blob id.

    Raises:
        ShapeError: If the commit is not exactly one modified path.
    """
    raw = _git(
        "-c",
        "core.quotePath=false",
        "-c",
        "diff.renames=false",
        "diff-tree",
        "-r",
        "--no-commit-id",
        "--raw",
        "-z",
        parent,
        sha,
        cwd=root,
    )
    fields = [field for field in raw.split("\0") if field != ""]
    # One entry is a `:` metadata field and its path; two fields exactly.
    if len(fields) != 2:  # noqa: PLR2004  # one entry is one meta field and one path
        raise ShapeError(
            f"{sha[:12]} touches {len(fields) // 2} path(s), expected exactly 1 — "
            "a ratification flip is one ADR file and nothing else"
        )
    meta = fields[0].lstrip(":").split()
    if len(meta) != _RAW_FIELDS:
        raise ShapeError(f"{sha[:12]}: unreadable diff entry {fields[0]!r}")
    src_mode, dst_mode, src_blob, dst_blob, status = meta
    if status != "M":
        raise ShapeError(
            f"{sha[:12]} is a '{status}' entry, not a modification — a ratification flip "
            "edits an ADR that is present in both trees"
        )
    if src_mode != dst_mode:
        raise ShapeError(f"{sha[:12]} changes the file mode {src_mode} → {dst_mode}")
    return fields[1], src_blob, dst_blob


def check_commit(root: Path, commit: str) -> str:
    """Return the flipped ADR's path if ``commit`` is exactly a ratification flip.

    The test is a **reconstruction**, not a diff pattern: the parent's blob goes
    through :func:`render_ratified` and is compared byte for byte with the
    child's. Everything the commit could carry beyond that is excluded by
    requiring exactly one modified path under ``docs/adr/NNNN-*.md``.

    Args:
        root: The work tree root.
        commit: The commit to test.

    Returns:
        The repository-relative path of the ratified ADR.

    Raises:
        ShapeError: If ``commit`` is not exactly a ratification flip, naming why.
    """
    sha, parent = _sole_parent(root, commit)
    path, src_blob, dst_blob = _sole_modified_path(root, parent, sha)
    adr_number(path)
    if _blob(root, dst_blob) != render_ratified(_blob(root, src_blob)):
        raise ShapeError(
            "the file is not its parent with the one Status line flipped — some other "
            "byte changed, so this commit carries content no review has read"
        )
    return path


# --------------------------------------------------------------------------- #
# Production                                                                   #
# --------------------------------------------------------------------------- #


def _refuse_unless_ready(root: Path) -> None:
    """Refuse to flip from a branch or tree that cannot carry the commit.

    A clean tree, not "clean apart from the ADR": :func:`_ratify` transforms the
    file's *committed* content, so an uncommitted edit would be left out of the
    commit while :func:`check_commit` — which rebuilds from that same committed
    content — still passed. Refusing up front says so; the alternative is a
    commit that exists and silently is not the file the author was looking at.

    Args:
        root: The work tree root.

    Raises:
        ShapeError: If HEAD is detached, on ``main``, or the tree is dirty.
    """
    branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=root).strip()
    if branch == "HEAD":
        raise ShapeError("detached HEAD — check out the ADR's branch first")
    if branch == "main":
        raise ShapeError("on main; the ratification flip belongs on the ADR's PR branch")
    if _git("status", "--porcelain", cwd=root).strip():
        raise ShapeError("working tree is dirty (tracked or untracked) — commit or stash first")


def _proposed_adrs(root: Path, paths: Sequence[str]) -> list[str]:
    """Return those of ``paths`` whose header still reads ``Proposed`` at HEAD.

    The test is a **prefix** here, where :func:`render_ratified` demands exact
    equality, and the asymmetry is deliberate: both fail closed, in opposite
    directions. The transform must not rewrite a line carrying a caveat, so it
    refuses anything but the bare token; the guard must not wave through an ADR
    whose status is ``Proposed`` with a caveat attached, so it catches anything
    that starts with it.

    Args:
        root: The work tree root.
        paths: Repository-relative paths, already filtered to numbered ADRs.

    Returns:
        The paths still standing ``Proposed``, in the order given.
    """
    still = []
    for path in paths:
        lines = _git("show", f"HEAD:{path}", cwd=root).split("\n")
        end = header_end(lines)
        if any(lines[i].startswith(_STATUS_PROPOSED) for i in range(end)):
            still.append(path)
    return still


def _locate_adr(root: Path) -> str:
    """Return the branch's one ADR still standing ``Proposed``.

    Args:
        root: The work tree root.

    Returns:
        The repository-relative path.

    Raises:
        ShapeError: If there is not exactly one.
    """
    # Narrow with one `git grep` before reading headers: the corpus is in the
    # hundreds and only a couple of files carry the string anywhere. Exit 1 is
    # "no match", not a failure, so it is read rather than raised on.
    grep = _run_git(
        ["grep", "-l", "-F", "-e", _STATUS_PROPOSED, "HEAD", "--", _ADR_DIR + "/"], cwd=root
    )
    if grep.returncode not in (0, 1):
        raise ShapeError("git grep: " + grep.stderr.decode("utf-8", "replace").strip())
    tracked = [
        path
        for line in grep.stdout.decode("utf-8", "replace").splitlines()
        for path in [line.partition(":")[2]]
        if _ADR_PATH_RE.match(path)
    ]
    candidates = _proposed_adrs(root, tracked)
    if len(candidates) != 1:
        raise ShapeError(
            f"expected exactly one ADR standing 'Proposed' under {_ADR_DIR}/, found "
            f"{len(candidates)}: {candidates} — name it with --adr"
        )
    return candidates[0]


_MESSAGE = """docs(adr): ratify ADR-{number:04d}

The ratification flip (ADR-0165 §2): the header's one `- Status: Proposed` line
becomes `- Status: Accepted`, in one ADR file, and no other byte changes. That
one-line shape is the whole of what makes this commit exempt from a fresh review
round (ADR-0165 §3), and `scripts/ship.sh` verifies it by rebuilding this file
from its parent's rather than by trusting the message.

Refs: ADR-{number:04d}
"""


def _ratify(args: argparse.Namespace) -> int:
    """Produce the ratification flip commit. See :func:`main`.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit status.

    Raises:
        ShapeError: If the flip cannot be made, or the commit made is not one the
            recogniser accepts.
    """
    root = repo_root(Path.cwd())
    _refuse_unless_ready(root)

    path: str = args.adr or _locate_adr(root)
    number = adr_number(path)
    rendered = render_ratified(_git("show", f"HEAD:{path}", cwd=root))

    if args.dry_run:
        print(f"would ratify {path} as ADR-{number:04d}")
        print(f"  {_STATUS_PROPOSED} → {_STATUS_ACCEPTED}, one line, nothing else")
        return 0

    before = _git("rev-parse", "HEAD", cwd=root).strip()
    # Everything that touches the repository is inside one try, and the recovery
    # is the same for all of it: put the branch back where it was. The producer
    # verifies itself against the recogniser at the end, because a flip commit
    # the exemption does not recognise is worse than no exemption — it costs a
    # round *and* reads as a bug in ship — and a half-applied edit left behind by
    # a hook that rejected the commit is worse than either. Restoring is safe
    # precisely because `_refuse_unless_ready` verified the tree clean.
    try:
        (root / path).write_text(rendered, encoding="utf-8")
        _git("add", "--", path, cwd=root)
        _git("commit", "-m", _MESSAGE.format(number=number), cwd=root)
        check_commit(root, "HEAD")
    except (ShapeError, OSError) as exc:
        # OSError is in here for the write before the commit: a full disk or an
        # I/O error there leaves the file edited and no commit, which is exactly
        # the half-applied state this recovery exists to undo, and it is not a
        # ShapeError.
        #
        # `reset --hard` restores tracked files and nothing else, so on its own
        # it leaves behind anything the failed attempt created but never tracked
        # — typically a file a commit hook wrote on its way to rejecting the
        # commit. That makes the *next* run refuse on a dirty tree while this
        # message says "restored". So the residue is REPORTED and never deleted:
        # the clean-tree precondition is a point-in-time check, so a file that
        # appeared after it — another process, an editor, a person — would be in
        # that set, and destroying a user's file to tidy up after a failed commit
        # is a far worse outcome than the dirty tree it tidies. This run creates
        # no untracked path of its own, so there is nothing here it may delete.
        _git("reset", "--hard", before, cwd=root)
        residue = _git("status", "--porcelain", cwd=root).strip()
        restored = f" — the branch is restored to {before[:12]}"
        if residue:
            restored += (
                f", but {len(residue.splitlines())} path(s) are left in the working "
                f"tree and none of them is this run's to delete; inspect and clear "
                f"them before retrying"
            )
        raise ShapeError(f"{exc}{restored}") from exc

    print(f"ratified {path} as ADR-{number:04d} — {_STATUS_PROPOSED} → {_STATUS_ACCEPTED}")
    return 0


# --------------------------------------------------------------------------- #
# The ready guard (ADR-0165 §5, issue #1044)                                   #
# --------------------------------------------------------------------------- #


def _gh(*args: str, cwd: Path) -> str:
    """Run gh in ``cwd`` and return its stdout.

    Args:
        *args: The gh arguments.
        cwd: The directory to run in.

    Returns:
        Standard output, decoded as UTF-8 and stripped.

    Raises:
        ShapeError: If gh is missing or fails.
    """
    found = shutil.which("gh")
    if found is None:
        raise ShapeError("gh CLI not found on PATH")
    completed = subprocess.run(  # noqa: S603  # fixed argv, no shell, resolved binary
        [found, *args],
        cwd=str(cwd),
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ShapeError(
            "gh " + " ".join(args) + ": " + completed.stderr.decode("utf-8", "replace").strip()
        )
    return completed.stdout.decode("utf-8", "replace").strip()


def _refuse_unless_pr_head_is_local_head(root: Path) -> None:
    """Refuse while the PR's head is not the commit this guard judges.

    Everything here reads the LOCAL ``HEAD``, so a commit GitHub has not seen
    would make the guard describe a tree that is not the PR's — and the direction
    that fails is the permissive one: ratify locally, run the recipe before
    pushing, and a PR still carrying ``- Status: Proposed`` is marked ready by a
    guard that just certified a file only this clone holds. That is issue #1044's
    failure with an extra step, so it is refused rather than warned about.

    It is called **twice**: once up front, so a stale head fails fast and with a
    message rather than after a network fetch, and once immediately before the
    guard returns success, so the window between the evidence and the act is the
    smallest this shape allows. ``ship`` re-reads ``headRefOid`` before its own
    external write for exactly this reason.

    **The window is narrowed, not closed, and that is worth saying plainly.** The
    documented recipe is two commands — this check, then ``gh pr ready`` — so a
    push landing between the process exiting and GitHub receiving the flag is
    outside anything this script can observe. Closing it entirely would take a
    conditional flip GitHub does not offer. What the second read buys is the
    difference between a window spanning a fetch and a diff and one spanning a
    process exit.

    Args:
        root: The work tree root.

    Raises:
        ShapeError: If the PR head is not local ``HEAD``.
    """
    sha = _git("rev-parse", "HEAD", cwd=root).strip()
    pr_sha = _gh("pr", "view", "--json", "headRefOid", "--jq", ".headRefOid", cwd=root)
    if not pr_sha:
        raise ShapeError("no PR found for this branch — open one first (gh pr create)")
    if pr_sha != sha:
        raise ShapeError(
            f"PR head is {pr_sha[:12]} but HEAD is {sha[:12]} — push first, or this "
            "guard would judge a commit the PR does not carry"
        )


def pr_adr_paths(root: Path) -> list[str]:
    """Return the numbered ADR documents this PR adds or modifies.

    The set is read against the PR's own base branch, fetched live, so it is the
    ADRs *this* PR is responsible for and not every ADR the branch happens to
    contain. ``docs/adr/template.md`` is not among them: it is not an ADR, and
    its header carries the literal ``- Status: Proposed | Accepted | …`` menu, so
    including it would refuse every PR that ever edits the template.

    Args:
        root: The work tree root.

    Returns:
        Repository-relative paths, added or modified.

    Raises:
        ShapeError: If the PR or its base cannot be resolved.
    """
    base_ref = _gh("pr", "view", "--json", "baseRefName", "--jq", ".baseRefName", cwd=root)
    if not base_ref:
        raise ShapeError("could not resolve the PR's base branch — open a PR first")
    _git("fetch", "--no-tags", "--quiet", "origin", base_ref, cwd=root)
    raw = _git(
        "-c",
        "core.quotePath=false",
        "-c",
        "diff.renames=false",
        "diff",
        "--name-status",
        "-z",
        "FETCH_HEAD...HEAD",
        cwd=root,
    )
    fields = [field for field in raw.split("\0") if field != ""]
    paths = []
    index = 0
    while index < len(fields):
        status = fields[index]
        # Rename detection is pinned off above, so no entry carries two paths.
        # An `R`/`C` here would mean the pin did not take and the fields are
        # misaligned; refuse rather than read the next status as a path.
        if status[:1] in ("R", "C"):
            raise ShapeError(f"unexpected rename entry {status!r} with rename detection off")
        if index + 1 >= len(fields):
            raise ShapeError("unreadable --name-status output: a status with no path")
        path = fields[index + 1]
        if status in ("A", "M") and _ADR_PATH_RE.match(path):
            paths.append(path)
        index += 2
    return paths


def _check_ready(_args: argparse.Namespace) -> int:
    """Refuse while an ADR this PR touches still reads ``Proposed``. See :func:`main`.

    Args:
        _args: Unused; the command takes none.

    Returns:
        The process exit status.

    Raises:
        ShapeError: If any touched ADR still stands ``Proposed``.
    """
    root = repo_root(Path.cwd())
    _refuse_unless_pr_head_is_local_head(root)
    still = _proposed_adrs(root, pr_adr_paths(root))
    # Re-read the PR head last: the evidence above is about the tree as it stood
    # when the fetch began, and `gh pr ready` acts on the PR as it stands now.
    _refuse_unless_pr_head_is_local_head(root)
    if still:
        listed = "\n       ".join(still)
        raise ShapeError(
            "this PR still carries an ADR standing 'Proposed':\n"
            f"       {listed}\n"
            "     ratify it before the PR leaves draft — `just adr-ratify` makes the flip,\n"
            "     and CONTRIBUTING.md → 'Finishing an ADR PR' carries the order (ADR-0165 §5)"
        )
    print("adr-ratify: no ADR on this PR stands 'Proposed'")
    return 0


def _check_shape(args: argparse.Namespace) -> int:
    """Print the flipped ADR's path if the commit is a ratification flip.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit status.
    """
    print(check_commit(repo_root(Path.cwd()), args.commit))
    return 0


def _parser() -> argparse.ArgumentParser:
    """Return the CLI parser.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        description="Produce and recognise the ADR ratification flip (ADR-0165)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ratify = sub.add_parser("ratify", help="make the ratification flip commit")
    ratify.add_argument("--adr", help="the ADR path (default: the branch's one Proposed ADR)")
    ratify.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")

    check = sub.add_parser("check-shape", help="is this commit exactly a ratification flip?")
    check.add_argument("commit", nargs="?", default="HEAD")

    sub.add_parser("check-ready", help="refuse if a touched ADR still reads Proposed")
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
        if args.command == "ratify":
            return _ratify(args)
        if args.command == "check-ready":
            return _check_ready(args)
        return _check_shape(args)
    except ShapeError as exc:
        print("adr-ratify: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
