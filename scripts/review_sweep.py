#!/usr/bin/env python3
"""Retire the ``.review/`` artifacts no live branch can still use.

Every review round writes an artifact under ``.review/`` and the directory is
per-clone and never pruned, so a clone that has held a dozen lanes holds every
round of all of them (issue #1391). That is not merely untidy. Two mechanisms
read the directory, and both read it *by glob*:

* ``scripts/ship.sh`` selects the artifact covering the PR head's content, over
  ``.review/*.md`` (ADR-0027 §2);
* ``scripts/codex-review.sh`` derives ADR-0138's round number and churn ratio
  from the **distinct reviewed trees recorded for this branch name**, over the
  same glob.

The second is why this cannot sweep by "looks old". The aggregate is scoped by
the recorded ``branch=`` field, and branch names repeat — ``dev/...`` slugs are
reused across batches — so a merged lane's leftovers inflate the round count of
the next lane that happens to share its name, and sweeping a *live* branch's
artifacts would reset the count ADR-0138 §1's handoff threshold is read off.

**The classifier is therefore about refs, not about dates.** Each artifact
records the branch and the commit it reviewed, and lands in one of:

``live``
    Some ref still holds it — the recorded branch exists locally or on a remote,
    or the recorded commit is contained in a ref other than the default branch.
    Kept, always.
``merged``
    The recorded commit is an ancestor of the default branch. Sweepable.
``stale``
    Neither: the branch is gone and no ref holds the commit. This is what a
    rebase-merge leaves behind, and so it is the common case rather than the
    exotic one — rebase-merge rewrites the commits, so a landed lane's reviewed
    sha is in no history at all.
``unreadable``
    No parseable provenance line. **Kept**, and reported: an artifact this cannot
    read is one it cannot classify, and the fail-closed direction is to leave it.

**Archive is the default and deletion is opt-in, but neither is forbidden by an
ADR.** ADR-0015 §1, ADR-0020 §3 and ADR-0027 §2 all treat an artifact as evidence
for the local ``ship`` step, and ``.gitignore`` says so in as many words — the
*record* of a review is the comment ``ship`` posts to the PR, which is on GitHub
and outlives every clone. ADR-0138's aggregate is likewise carried into that
comment at ship time. So nothing here is history, and ``--delete`` contradicts no
ratified decision. The default is still ``--archive``, because a local move is
recoverable and a mistaken classification then costs nothing.

Both actions have the same effect on the two mechanisms above: ``.review/*.md``
is not recursive, so an archived artifact is as invisible to them as a deleted
one.

**Disposition snapshots follow their artifact, but only when nothing else needs
them.** ``.review/dispositions/<loop>-<persona>-<tree>.md`` is what ``ship``
publishes beside a verdict (ADR-0025 §4), and it fails closed on a snapshot that
is missing *or* ambiguous. A snapshot is swept only when no retained artifact
carries its ``(loop, persona, tree)``, so a sweep can never strand a retained
artifact without its evidence.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

#: The review directory, relative to the repository root.
REVIEW_DIR = ".review"
#: Where an archived artifact goes. Below `.review/`, which `.gitignore` already
#: covers wholesale, so this needs no ignore entry of its own.
ARCHIVE_DIR = "archive"
#: The disposition snapshots `ship` publishes beside a verdict (ADR-0025 §4).
DISPOSITIONS_DIR = "dispositions"
#: Candidate default branches, most authoritative first: an artifact's commit is
#: "merged" when it is an ancestor of the first of these the clone actually has.
DEFAULT_BRANCHES = ("origin/main", "main")
#: The refs that being contained in does NOT make an artifact live — being on the
#: integration branch is precisely what makes it sweepable.
_DEFAULT_REFS = ("refs/heads/main", "refs/remotes/origin/main")

#: One provenance field, matched the way `ship.sh`'s `provenance_field` matches
#: it: the name pinned by leading whitespace so `base_sha=` is never read as
#: `sha=`, and the value taken to the next whitespace so a malformed field
#: mismatches instead of silently truncating to something well-formed.
_FIELD = "(?<=[\\s]){name}=([^\\s]*)"


#: The two states a sweep acts on. Everything else — including anything this
#: could not read — is kept.
SWEEPABLE = frozenset({"merged", "stale"})


class SweepError(Exception):
    """The sweep could not proceed."""


class Verdict(NamedTuple):
    """One artifact's classification.

    Attributes:
        path: The artifact.
        state: ``live``, ``merged``, ``stale`` or ``unreadable``.
        detail: Why, in one phrase.
        key: The ``(loop_id, persona, tree)`` its disposition snapshot is keyed
            on, or ``None`` when the provenance did not carry all three.
    """

    path: Path
    state: str
    detail: str
    key: tuple[str, str, str] | None


def provenance_field(name: str, line: str) -> str:
    """Read one provenance field from an artifact's first line.

    Args:
        name: The field name.
        line: The provenance comment.

    Returns:
        The field's value, or the empty string when it is absent.
    """
    match = re.search(_FIELD.format(name=re.escape(name)), line)
    return match.group(1) if match else ""


def _git(*args: str, repo: Path) -> str:
    """Run git in ``repo`` and return its stdout.

    Args:
        *args: The git arguments.
        repo: The repository root.

    Returns:
        Standard output, with the trailing newline removed.

    Raises:
        SweepError: If git is missing.
    """
    binary = shutil.which("git")
    if binary is None:
        raise SweepError("git not found on PATH")
    completed = subprocess.run(  # noqa: S603  # fixed argv, no shell, resolved binary
        [binary, *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.rstrip("\n") if completed.returncode == 0 else ""


def _git_ok(*args: str, repo: Path) -> bool:
    """Run git in ``repo`` and report only whether it succeeded.

    Args:
        *args: The git arguments.
        repo: The repository root.

    Returns:
        True when git exited zero.

    Raises:
        SweepError: If git is missing.
    """
    binary = shutil.which("git")
    if binary is None:
        raise SweepError("git not found on PATH")
    completed = subprocess.run(  # noqa: S603  # fixed argv, no shell, resolved binary
        [binary, *args], cwd=str(repo), capture_output=True, check=False
    )
    return completed.returncode == 0


class Refs:
    """What the repository's refs currently hold, read once per sweep."""

    def __init__(self, repo: Path) -> None:
        """Read the ref state.

        Args:
            repo: The repository root.
        """
        self.repo = repo
        self.branches: set[str] = set()
        for line in _git(
            "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes", repo=repo
        ).splitlines():
            if line.startswith("refs/heads/"):
                self.branches.add(line.removeprefix("refs/heads/"))
            elif line.startswith("refs/remotes/"):
                # `refs/remotes/origin/feature/x` -> `feature/x`: the remote name
                # is one component and the rest is the branch as an artifact
                # records it.
                rest = line.removeprefix("refs/remotes/").split("/", 1)
                if len(rest) == 2:  # noqa: PLR2004  # a remote name and a branch
                    self.branches.add(rest[1])
        self.default = next(
            (b for b in DEFAULT_BRANCHES if _git_ok("rev-parse", "--verify", b, repo=repo)),
            None,
        )

    def has_branch(self, name: str) -> bool:
        """Report whether a branch of that name exists locally or on a remote.

        Args:
            name: The branch name as an artifact records it.

        Returns:
            True when some ref carries it.
        """
        return name in self.branches

    def is_merged(self, sha: str) -> bool:
        """Report whether a commit is an ancestor of the default branch.

        Args:
            sha: The commit.

        Returns:
            True when it is. False when the commit is unknown, or there is no
            default branch to compare against.
        """
        if self.default is None:
            return False
        return _git_ok("merge-base", "--is-ancestor", sha, self.default, repo=self.repo)

    def held_by_a_ref(self, sha: str) -> bool:
        """Report whether any ref other than the default branch contains a commit.

        Args:
            sha: The commit.

        Returns:
            True when at least one such ref does.
        """
        if not _git_ok("cat-file", "-e", f"{sha}^{{commit}}", repo=self.repo):
            return False
        holders = _git(
            "for-each-ref",
            "--contains",
            sha,
            "--format=%(refname)",
            "refs/heads",
            "refs/remotes",
            repo=self.repo,
        ).splitlines()
        return any(ref not in _DEFAULT_REFS for ref in holders)


def classify(artifact: Path, refs: Refs) -> Verdict:
    """Classify one artifact against the repository's refs.

    Args:
        artifact: The artifact file.
        refs: The ref state.

    Returns:
        The verdict.
    """
    try:
        with artifact.open(encoding="utf-8", errors="replace") as handle:
            provenance = handle.readline()
    except OSError as exc:
        return Verdict(artifact, "unreadable", str(exc), None)

    branch = provenance_field("branch", provenance)
    sha = provenance_field("sha", provenance)
    loop = provenance_field("loop_id", provenance)
    persona = provenance_field("persona", provenance)
    tree = provenance_field("tree", provenance)
    key = (loop, persona, tree) if loop and persona and tree else None

    if not branch and not sha:
        return Verdict(artifact, "unreadable", "no branch or sha in the provenance line", key)
    if branch and refs.has_branch(branch):
        return Verdict(artifact, "live", f"branch {branch} still exists", key)
    if sha and refs.held_by_a_ref(sha):
        return Verdict(artifact, "live", f"{sha[:12]} is held by a ref", key)
    if sha and refs.is_merged(sha):
        return Verdict(artifact, "merged", f"{sha[:12]} is on {refs.default}", key)
    gone = f"branch {branch} is gone" if branch else f"{sha[:12]} is in no ref"
    return Verdict(artifact, "stale", gone, key)


def snapshots_to_sweep(
    review: Path, swept: Iterable[Verdict], retained: Iterable[Verdict]
) -> list[Path]:
    """Return the disposition snapshots whose artifacts are all being swept.

    Args:
        review: The review directory.
        swept: The artifacts being archived or deleted.
        retained: The artifacts staying.

    Returns:
        The snapshot files safe to sweep, sorted.
    """
    keep = {v.key for v in retained if v.key is not None}
    wanted = {v.key for v in swept if v.key is not None} - keep
    found: list[Path] = []
    for snapshot in sorted((review / DISPOSITIONS_DIR).glob("*.md")):
        try:
            with snapshot.open(encoding="utf-8", errors="replace") as handle:
                header = handle.readline()
        except OSError:
            continue  # unreadable is unclassifiable, and unclassifiable is kept
        key = (
            provenance_field("loop_id", header),
            provenance_field("persona", header),
            provenance_field("tree", header),
        )
        if all(key) and key in wanted:
            found.append(snapshot)
    return found


def _act(paths: Sequence[Path], review: Path, *, delete: bool, dry_run: bool) -> None:
    """Archive or delete the swept files.

    Args:
        paths: The files to act on.
        review: The review directory.
        delete: Delete rather than archive.
        dry_run: Decide everything and change nothing.

    Raises:
        SweepError: If a file cannot be moved or removed.
    """
    if dry_run or not paths:
        return
    archive = review / ARCHIVE_DIR
    try:
        for path in paths:
            if delete:
                path.unlink()
            else:
                # Mirror the layout under the archive, so a swept disposition
                # snapshot does not collide with a swept artifact of one name.
                destination = archive / path.relative_to(review)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(destination))
    except OSError as exc:
        raise SweepError(f"could not sweep the review directory: {exc}") from exc


def _report(
    verdicts: Sequence[Verdict], snapshots: Sequence[Path], *, delete: bool, dry_run: bool
) -> None:
    """Print the plan or the result.

    Args:
        verdicts: Every artifact's classification.
        snapshots: The disposition snapshots being swept.
        delete: Whether the action is deletion.
        dry_run: Whether anything was actually done.
    """
    action = "delete" if delete else "archive"
    verb = f"would {action}" if dry_run else f"{action}d"
    for verdict in sorted(verdicts, key=lambda v: (v.state, v.path.name)):
        mark = verb if verdict.state in SWEEPABLE else "keep"
        print(f"{mark:>14}  {verdict.path.name}  [{verdict.state}] {verdict.detail}")
    states = ("live", "merged", "stale", "unreadable")
    counts = {state: sum(1 for v in verdicts if v.state == state) for state in states}
    print(
        f"\n{len(verdicts)} artifact(s): {counts['live']} live, {counts['merged']} merged, "
        f"{counts['stale']} stale, {counts['unreadable']} unreadable; "
        f"{len(snapshots)} disposition snapshot(s) {verb}."
    )


def _sweep(args: argparse.Namespace) -> int:
    """Run the sweep.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit status.

    Raises:
        SweepError: If there is no review directory, or a file cannot be swept.
    """
    repo = Path(args.repo).resolve()
    review = repo / REVIEW_DIR
    if not review.is_dir():
        raise SweepError(f"no {REVIEW_DIR}/ in {repo}; nothing to sweep")
    refs = Refs(repo)
    verdicts = [classify(a, refs) for a in sorted(review.glob("*.md"))]
    swept = [v for v in verdicts if v.state in SWEEPABLE]
    retained = [v for v in verdicts if v.state not in SWEEPABLE]
    snapshots = snapshots_to_sweep(review, swept, retained)
    _act([v.path for v in swept] + snapshots, review, delete=args.delete, dry_run=args.dry_run)
    _report(verdicts, snapshots, delete=args.delete, dry_run=args.dry_run)
    return 0


def _parser() -> argparse.ArgumentParser:
    """Return the CLI parser.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        description="Retire the .review/ artifacts no live branch can still use (issue #1391)."
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--archive", action="store_true", help="move them under .review/archive/ (the default)"
    )
    action.add_argument("--delete", action="store_true", help="remove them instead")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    parser.add_argument("--repo", default=".", help="the clone to sweep")
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
        return _sweep(args)
    except SweepError as exc:
        print(f"review-sweep: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
