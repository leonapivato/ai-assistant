#!/usr/bin/env python3
"""Produce and recognise the mechanical ADR **ratify** commit (ADR-0165).

An ADR lane's PR is the ADR alone, authored under its slug — ``docs/adr/<slug>.md``
— with ``XXXX`` standing in for the number it does not yet have, and reviewed as
*Proposed, unnumbered*. At merge, one commit takes ``max(main) + 1``, renames the
file onto it, substitutes the number, flips ``Status`` to ``Accepted`` and stamps
the date. **Nothing else.** That commit is exempt from a fresh Codex round
precisely because it carries no content a reviewer could read differently
(ADR-0165 §4).

The exemption is only as safe as the recognition, so this module is *one*
implementation used from both ends:

``ratify``
    produces the commit, from the ADR file's committed content.
``check-shape``
    decides whether a commit *is* one, by rebuilding the child from the parent
    with :func:`render_ratified` and comparing bytes. ``scripts/ship.sh`` shells
    out to this subcommand rather than reimplementing the test — issue #751
    records what a hand-built replica of a ship-side rule costs when it drifts.

Because the recogniser rebuilds rather than pattern-matches the diff, "exactly
that shape" is not an approximation of the rule: a ratify commit that changed one
further byte anywhere in the file, or touched any second path, cannot be
reconstructed from its parent and is not recognised.

Stdlib only, and deliberately no syntax newer than Python 3.9, so ``ship.sh`` can
reach it through a bare ``python3`` without the project's own interpreter.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

#: The token an unnumbered ADR carries wherever its own number will go. It is
#: **reserved**: an ADR that needs to display the literal placeholder — quoting
#: the template, exhibiting the status grammar — writes it some other way, and
#: :func:`render_ratified` refuses a file with any ``XXXX`` left after the
#: substitution rather than shipping a half-numbered document (ADR-0165 §3).
PLACEHOLDER = "XXXX"

#: The H1 of an unnumbered ADR: ``# XXXX. <title>``. The ratified form is
#: ``# <n>. <title>`` with the number **unpadded**, which is what the whole
#: corpus writes and what ``scripts/project_status.py`` compares against the
#: filename's padded one.
_UNNUMBERED_HEADING_RE = re.compile("^# " + PLACEHOLDER + r"\. (\S.*)$")

#: A self-reference in an unnumbered ADR. Padded on substitution, because that is
#: the citation form ADR-0088 §1 checks and every other ADR writes.
_SELF_REFERENCE = "ADR-" + PLACEHOLDER

_STATUS_PROPOSED = "- Status: Proposed"
_STATUS_ACCEPTED = "- Status: Accepted"
_DATE_PREFIX = "- Date: "
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: ``0164-<slug>.md`` — a ratified ADR's filename.
_NUMBERED_NAME_RE = re.compile(r"^(\d{4})-(.+)\.md$")

_ADR_DIR = "docs/adr"

#: The corpus's numbering width, and so the largest number an ADR can take.
_MAX_NUMBER = 9999

#: ``git diff-tree -z --name-status`` emits one status and one path per entry, so
#: two entries — a delete and an add — are four NUL-separated fields.
_RENAME_FIELDS = 4

#: Not an ADR under any numbering: the template is the corpus's one permanent
#: unnumbered file, so auto-detection and the shape test both exclude it by name.
_TEMPLATE_NAME = "template.md"


class ShapeError(Exception):
    """The input is not in the shape this module requires.

    Every refusal here raises one, so a caller distinguishes "not a ratify
    commit" from "this script broke" by exception type rather than by reading a
    message.
    """


# --------------------------------------------------------------------------- #
# The transform — the single definition of "exactly that shape"                #
# --------------------------------------------------------------------------- #


def header_end(lines: Sequence[str]) -> int:
    """Return the index of the first line after an ADR's header block.

    The header ends at the first level-2 heading, which is ``## Context`` in
    every ADR the corpus holds. ``Status`` and ``Date`` are looked for *inside*
    those bounds, so a quoted ``- Status: Proposed`` in the body — ADRs quote
    each other's header lines constantly — is neither counted nor rewritten.

    Args:
        lines: The document's lines, without terminators.

    Returns:
        The index of the first ``## `` line, or ``len(lines)`` if there is none.
    """
    for index, line in enumerate(lines):
        if line.startswith("## "):
            return index
    return len(lines)


def _sole_index(lines: Sequence[str], end: int, predicate: str, what: str) -> int:
    """Return the one header line index satisfying ``predicate``.

    Args:
        lines: The document's lines.
        end: The exclusive end of the header block.
        predicate: A prefix the line must start with.
        what: What to call it in the error message.

    Returns:
        The index.

    Raises:
        ShapeError: If the header carries other than exactly one such line.
    """
    found = [i for i in range(end) if lines[i].startswith(predicate)]
    if len(found) != 1:
        raise ShapeError(f"the header carries {len(found)} {what} lines, expected exactly 1")
    return found[0]


def render_ratified(text: str, number: int, date: str) -> str:
    """Return ``text`` as it stands once ratified under ``number`` on ``date``.

    This is the whole of the ratify commit's content change, and the only
    definition of it. Four edits:

    1. the H1 ``# XXXX. <title>`` becomes ``# <number>. <title>``;
    2. the header's one ``- Status: Proposed`` becomes ``- Status: Accepted``;
    3. the header's one ``- Date: …`` becomes ``- Date: <date>``;
    4. every ``ADR-XXXX`` becomes ``ADR-<number, zero-padded to four>``.

    Args:
        text: The unnumbered, ``Proposed`` ADR's content.
        number: The number being taken.
        date: The ratification date, ``YYYY-MM-DD``.

    Returns:
        The ratified content.

    Raises:
        ShapeError: If ``text`` is not in the unnumbered ``Proposed`` shape, if
            ``date`` is not an ISO date, if ``number`` is out of range, or if any
            ``XXXX`` survives the substitution.
    """
    if not 0 < number <= _MAX_NUMBER:
        raise ShapeError(f"ADR number out of range: {number}")
    if not _ISO_DATE_RE.match(date):
        raise ShapeError("date is not YYYY-MM-DD: " + repr(date))

    lines = text.split("\n")
    heading = _UNNUMBERED_HEADING_RE.match(lines[0])
    if heading is None:
        raise ShapeError(
            "first line is not an unnumbered ADR heading "
            "'# " + PLACEHOLDER + ". <title>': " + repr(lines[0])
        )
    lines[0] = f"# {number}. {heading.group(1)}"

    end = header_end(lines)
    status_at = _sole_index(lines, end, _STATUS_PROPOSED, repr(_STATUS_PROPOSED))
    lines[status_at] = _STATUS_ACCEPTED
    date_at = _sole_index(lines, end, _DATE_PREFIX, repr(_DATE_PREFIX.strip()))
    lines[date_at] = _DATE_PREFIX + date

    rendered = "\n".join(lines).replace(_SELF_REFERENCE, f"ADR-{number:04d}")
    if PLACEHOLDER in rendered:
        raise ShapeError(
            "'" + PLACEHOLDER + "' survives the substitution — it is reserved for this ADR's "
            "own number, so a displayed placeholder has to be written some other way"
        )
    return rendered


def slug_of(path: str) -> str:
    """Return an unnumbered ADR path's slug: ``docs/adr/a-b.md`` → ``a-b``.

    Args:
        path: A repository-relative path.

    Returns:
        The slug.

    Raises:
        ShapeError: If ``path`` is not an unnumbered ADR file under ``docs/adr``.
    """
    parent, _, name = path.rpartition("/")
    if parent != _ADR_DIR or not name.endswith(".md"):
        raise ShapeError("not a markdown file under " + _ADR_DIR + "/: " + repr(path))
    if name == _TEMPLATE_NAME:
        raise ShapeError("the ADR template is not an ADR")
    if _NUMBERED_NAME_RE.match(name):
        raise ShapeError("already numbered: " + repr(path))
    return name[: -len(".md")]


def ratified_path(slug: str, number: int) -> str:
    """Return the repository-relative path a slug takes once numbered."""
    return f"{_ADR_DIR}/{number:04d}-{slug}.md"


# --------------------------------------------------------------------------- #
# git                                                                          #
# --------------------------------------------------------------------------- #


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
    completed = subprocess.run(  # noqa: S603  # fixed argv, no shell
        ["git", *args],  # noqa: S607  # git is resolved from PATH, as everywhere here
        cwd=str(cwd),
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ShapeError(
            "git " + " ".join(args) + ": " + completed.stderr.decode("utf-8", "replace").strip()
        )
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ShapeError("git " + " ".join(args) + ": output is not UTF-8") from exc


def _is_ancestor(root: Path, maybe_ancestor: str, rev: str) -> bool:
    """Return whether ``maybe_ancestor`` is contained in ``rev``'s history.

    Args:
        root: The work tree root.
        maybe_ancestor: The commit that may be contained.
        rev: The commit that may contain it.

    Returns:
        True if it is an ancestor (or the same commit).

    Raises:
        ShapeError: If git fails for any reason other than answering "no".
    """
    completed = subprocess.run(  # noqa: S603  # fixed argv, no shell
        ["git", "merge-base", "--is-ancestor", maybe_ancestor, rev],  # noqa: S607
        cwd=str(root),
        capture_output=True,
        check=False,
    )
    if completed.returncode not in (0, 1):
        raise ShapeError(
            "git merge-base --is-ancestor: " + completed.stderr.decode("utf-8", "replace").strip()
        )
    return completed.returncode == 0


def repo_root(start: Path) -> Path:
    """Return the work tree root containing ``start``."""
    return Path(_git("rev-parse", "--show-toplevel", cwd=start).strip())


def _blob(root: Path, rev: str, path: str) -> str:
    """Return a file's content at a revision."""
    return _git("show", rev + ":" + path, cwd=root)


def _next_number(root: Path, rev: str) -> int:
    """Return the number an ADR merging onto ``rev`` takes: its maximum plus one.

    One definition, called by the producer and by the recogniser, so "the number
    is max + 1" is a property a commit *has* rather than a rule the producer was
    trusted to have followed. Reading it from the ratify commit's own parent is
    what makes it checkable at all: the recogniser has no access to whatever
    `main` looked like when the commit was made, and §2 requires the commit to be
    made on a branch already rebased onto it.

    Args:
        root: The work tree root.
        rev: Any revision ``git ls-tree`` accepts.

    Returns:
        The next number.
    """
    return max(_adr_numbers(root, rev), default=0) + 1


def _adr_numbers(root: Path, rev: str) -> set[int]:
    """Return every ADR number present under ``docs/adr`` at ``rev``.

    Args:
        root: The work tree root.
        rev: Any revision ``git ls-tree`` accepts.

    Returns:
        The numbers, read from the filenames alone.
    """
    listing = _git("ls-tree", "--name-only", rev, _ADR_DIR + "/", cwd=root)
    numbers = set()
    for line in listing.splitlines():
        match = _NUMBERED_NAME_RE.match(line.rpartition("/")[2])
        if match is not None:
            numbers.add(int(match.group(1)))
    return numbers


# --------------------------------------------------------------------------- #
# Recognition                                                                  #
# --------------------------------------------------------------------------- #


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


def _renamed_pair(root: Path, parent: str, sha: str) -> tuple[str, str]:
    """Return the ``(deleted, added)`` paths of a two-entry commit.

    Rename detection is pinned **off** and paths are left unquoted, so the entry
    set is a function of the two commits alone rather than of whatever config the
    caller's clone carries. Off, a rename renders as its delete and its add — two
    entries this test then names individually, which is stricter than trusting a
    similarity score to have found the pair.

    Args:
        root: The work tree root.
        parent: The parent commit.
        sha: The commit.

    Returns:
        The deleted path and the added path.

    Raises:
        ShapeError: If the commit does not touch exactly one delete and one add.
    """
    raw = _git(
        "-c",
        "core.quotePath=false",
        "-c",
        "diff.renames=false",
        "diff-tree",
        "-r",
        "--no-commit-id",
        "--name-status",
        "-z",
        parent,
        sha,
        cwd=root,
    )
    fields = [field for field in raw.split("\0") if field != ""]
    if len(fields) != _RENAME_FIELDS:
        raise ShapeError(
            f"{sha[:12]} touches {len(fields) // 2} path(s), expected exactly 2 — "
            "the unnumbered file deleted and the numbered one added"
        )
    entries = {fields[0]: fields[1], fields[2]: fields[3]}
    if sorted(entries) != ["A", "D"]:
        raise ShapeError(f"{sha[:12]} is not one delete and one add: {sorted(entries)}")
    return entries["D"], entries["A"]


def _ratified_number(old_path: str, new_path: str) -> int:
    """Return the number the rename takes, checking the slug is untouched.

    Args:
        old_path: The deleted, unnumbered path.
        new_path: The added, numbered path.

    Returns:
        The ADR number.

    Raises:
        ShapeError: If the added path is not the same slug, numbered.
    """
    slug = slug_of(old_path)
    parent, _, name = new_path.rpartition("/")
    if parent != _ADR_DIR:
        raise ShapeError("the added file is not under " + _ADR_DIR + "/: " + repr(new_path))
    match = _NUMBERED_NAME_RE.match(name)
    if match is None:
        raise ShapeError("the added file is not a numbered ADR: " + repr(new_path))
    if match.group(2) != slug:
        raise ShapeError("the slug changed: " + repr(slug) + " → " + repr(match.group(2)))
    return int(match.group(1))


def _stamped_date(ratified: str) -> str:
    """Return the ``- Date:`` value the ratified file carries.

    Args:
        ratified: The added file's content.

    Returns:
        The date, verified to be an ISO date.

    Raises:
        ShapeError: If there is not exactly one such header line, or it is not an
            ISO date.
    """
    lines = ratified.split("\n")
    date = lines[_sole_index(lines, header_end(lines), _DATE_PREFIX, "'- Date:'")]
    value = date[len(_DATE_PREFIX) :]
    if not _ISO_DATE_RE.match(value):
        raise ShapeError("the stamped date is not YYYY-MM-DD: " + repr(value))
    return value


def check_commit(root: Path, commit: str) -> str:
    """Return the ratified ADR's path if ``commit`` is exactly a ratify commit.

    The test is a **reconstruction**, not a diff pattern: the parent's unnumbered
    file goes through :func:`render_ratified` and is compared byte for byte with
    the child's numbered one. Everything the commit could carry beyond that is
    excluded by requiring the tree diff to be exactly one delete and one add.

    Args:
        root: The work tree root.
        commit: The commit to test.

    Returns:
        The repository-relative path of the ratified ADR.

    Raises:
        ShapeError: If ``commit`` is not exactly a ratify commit, naming why.
    """
    sha, parent = _sole_parent(root, commit)
    old_path, new_path = _renamed_pair(root, parent, sha)
    number = _ratified_number(old_path, new_path)

    # The number must be exactly the parent tree's maximum plus one, which is
    # ADR-0165 §2's allocation rule tested rather than assumed. It subsumes the
    # collision case — a number already in use is at most the maximum, so it can
    # never be the maximum plus one — and it closes the case a bare
    # collision test leaves open: a number that skips ahead is *unused*, so it
    # collides with nothing, and it strands every number it jumped over.
    expected_number = _next_number(root, parent)
    if number != expected_number:
        raise ShapeError(
            f"ADR-{number:04d} is not the next number at {parent[:12]}: "
            f"max + 1 there is {expected_number:04d}"
        )

    ratified = _blob(root, sha, new_path)
    expected = render_ratified(_blob(root, parent, old_path), number, _stamped_date(ratified))
    if ratified != expected:
        raise ShapeError(
            "the added file is not the deleted one with the number substituted, the status "
            "flipped and the date stamped — some other byte changed"
        )
    return new_path


# --------------------------------------------------------------------------- #
# Production                                                                   #
# --------------------------------------------------------------------------- #


def _locate_adr(root: Path) -> str:
    """Return the branch's one unnumbered ADR path.

    Args:
        root: The work tree root.

    Returns:
        The repository-relative path.

    Raises:
        ShapeError: If there is not exactly one.
    """
    candidates = []
    for path in _git("ls-files", "--", _ADR_DIR + "/*.md", cwd=root).splitlines():
        try:
            slug_of(path)
        except ShapeError:  # a numbered ADR, or the template — the common case
            continue
        candidates.append(path)
    if len(candidates) != 1:
        raise ShapeError(
            f"expected exactly one unnumbered ADR under {_ADR_DIR}/, found "
            f"{len(candidates)}: {candidates} — name it with --adr"
        )
    return candidates[0]


def _refuse_unless_ready(root: Path) -> None:
    """Refuse to ratify from a branch or tree that cannot carry the commit.

    A clean tree, not "clean apart from the ADR": the transform reads the file's
    *committed* content, so an uncommitted edit would be left out of the commit
    while :func:`check_commit` — which rebuilds from that same committed content
    — still passed. Refusing up front says so; the alternative is a commit that
    exists and silently is not the file the author was looking at.

    Args:
        root: The work tree root.

    Raises:
        ShapeError: If HEAD is detached, on ``main``, or the tree is dirty.
    """
    branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=root).strip()
    if branch == "HEAD":
        raise ShapeError("detached HEAD — check out the ADR's branch first")
    if branch == "main":
        raise ShapeError("on main; the ratify commit belongs on the ADR's PR branch")
    if _git("status", "--porcelain", cwd=root).strip():
        raise ShapeError("working tree is dirty (tracked or untracked) — commit or stash first")


_MESSAGE = """docs(adr): ratify ADR-{number:04d}

Mechanical ratification (ADR-0165 §2): the number is max(main) + 1, the file
is renamed onto it, the ADR-{placeholder} self-references are substituted,
Status flips Proposed -> Accepted and the date is stamped. Nothing else
changes, which is what makes this commit exempt from a fresh review round
(ADR-0165 §4).

Refs: ADR-{number:04d}
"""


def _ratify(args: argparse.Namespace) -> int:
    """Produce the ratify commit. See :func:`main`."""
    root = repo_root(Path.cwd())
    _refuse_unless_ready(root)

    path: str = args.adr or _locate_adr(root)
    slug = slug_of(path)
    original = _blob(root, "HEAD", path)

    # The number is computed from HEAD's tree alone, because that is the tree the
    # recogniser can see. `main` is fetched only to prove HEAD is not behind it,
    # and the proof is ANCESTRY, not a comparison of ADR numbers: a base advance
    # that adds no ADR leaves the two number sets equal while the branch is just
    # as stale, and §2 puts this commit after the final rebase for the whole
    # state of the tree, not only for the part that decides the number.
    # `ship.sh`'s drill refuses on the same test for the same reason (issue
    # #751): a check computed against a base the branch does not contain answers
    # a question nobody asked.
    #
    # BOTH HALVES OF THAT ARE FIXED — a live fetch, and `main` — and neither is
    # an option, deliberately. A stale `origin/main` and an older `--base-branch`
    # each pass the ancestry test while `main` itself has moved, and the number
    # computed under either is then wrong in a way `check_commit` cannot see: it
    # reads the commit's parent, which is exactly the stale tree. Every escape
    # this run could offer is an escape from the one property the ship exemption
    # rests on, so it offers none.
    _git("fetch", "--no-tags", "--quiet", "origin", "main", cwd=root)
    base_sha = _git("rev-parse", "--verify", "FETCH_HEAD^{commit}", cwd=root).strip()
    if not _is_ancestor(root, base_sha, "HEAD"):
        raise ShapeError(
            f"'main' is at {base_sha[:12]} and this branch does not contain it — "
            f"rebase first, so the number is max + 1 on the tree that actually "
            f"merges (ADR-0165 §2)"
        )

    taken = _adr_numbers(root, "HEAD")
    expected = max(taken, default=0) + 1
    number: int = args.number if args.number is not None else expected
    if number != expected:
        raise ShapeError(
            f"ADR-{number:04d} is not the next number: max + 1 is {expected:04d}. "
            f"--number states the number you expect, it does not choose one"
        )

    date: str = args.date or time.strftime("%Y-%m-%d")
    rendered = render_ratified(original, number, date)
    new_path = ratified_path(slug, number)

    if args.dry_run:
        print(f"would ratify {path} → {new_path}")
        print(f"  number  {number:04d}  (max of the {len(taken)} on this branch, + 1)")
        print("  date    " + date)
        print("  status  Proposed → Accepted")
        return 0

    before = _git("rev-parse", "HEAD", cwd=root).strip()
    # Everything that touches the repository is inside one try, and the recovery
    # is the same for all of it: put the branch back where it was. The producer
    # verifies itself against the recogniser at the end, because a ratify commit
    # the exemption does not recognise is worse than no exemption — it costs a
    # round *and* reads as a bug in ship — and a half-applied rename left behind
    # by a hook that rejected the commit is worse than either. Restoring is safe
    # precisely because `_refuse_unless_ready` verified the tree clean.
    try:
        _git("mv", "--", path, new_path, cwd=root)
        (root / new_path).write_text(rendered, encoding="utf-8")
        _git("add", "--", new_path, cwd=root)
        _git("commit", "-m", _MESSAGE.format(number=number, placeholder=PLACEHOLDER), cwd=root)
        check_commit(root, "HEAD")
    except (ShapeError, OSError) as exc:
        # OSError is in here for the write between the rename and the commit: a
        # full disk or an I/O error there leaves the rename staged and no commit,
        # which is exactly the half-applied state this recovery exists to undo,
        # and it is not a ShapeError.
        _git("reset", "--hard", before, cwd=root)
        (root / new_path).unlink(missing_ok=True)
        raise ShapeError(f"{exc} — the branch is restored to {before[:12]}") from exc

    print(f"ratified {path} → {new_path} as ADR-{number:04d} ({date})")
    return 0


def _check_shape(args: argparse.Namespace) -> int:
    """Print the ratified ADR's path if HEAD is a ratify commit. See :func:`main`."""
    print(check_commit(repo_root(Path.cwd()), args.commit))
    return 0


def _parser() -> argparse.ArgumentParser:
    """Return the CLI parser."""
    parser = argparse.ArgumentParser(
        description="Produce and recognise the mechanical ADR ratify commit (ADR-0165)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ratify = sub.add_parser("ratify", help="produce the ratify commit")
    ratify.add_argument("--adr", help="the unnumbered ADR path (default: the branch's one)")
    ratify.add_argument(
        "--number", type=int, help="assert the number: it must be max + 1, or the run refuses"
    )
    ratify.add_argument("--date", help="the ratification date (default: today)")
    ratify.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")

    check = sub.add_parser("check-shape", help="is this commit exactly a ratify commit?")
    check.add_argument("commit", nargs="?", default="HEAD")
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
        return _check_shape(args)
    except ShapeError as exc:
        print("adr-ratify: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
