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
    No parseable provenance line — or a partial one that names a branch but no
    reviewed commit, which is the same thing for this purpose: with no commit
    there is no way to ask whether the content survives under another branch
    name. **Kept**, and reported: an artifact this cannot classify is one it
    leaves alone, and that is the direction that costs nothing when it is wrong.

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
#: Where a recorded `branch=` name is looked up.
_BRANCH_NAMESPACES = ("refs/heads", "refs/remotes")
#: The refs that being contained in does NOT make an artifact live — being on the
#: integration branch is precisely what makes it sweepable.
_DEFAULT_REFS = ("refs/heads/main", "refs/remotes/origin/main")

#: One provenance field, matched the way `ship.sh`'s `provenance_field` matches
#: it: the name pinned by leading whitespace so `base_sha=` is never read as
#: `sha=`, and the value taken to the next whitespace so a malformed field
#: mismatches instead of silently truncating to something well-formed.
_FIELD = "(?<=[\\s]){name}=([^\\s]*)"
#: A recorded commit id. A field that is not one cannot be asked about.
_SHA = re.compile(r"[0-9a-f]{40}")


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


def _git(*args: str, repo: Path, check: bool = False) -> str:
    """Run git in ``repo`` and return its stdout.

    Args:
        *args: The git arguments.
        repo: The repository root.
        check: Raise on a non-zero status instead of returning the empty string.
            Set it wherever "git said nothing" and "git could not answer" must not
            be the same result — a ref listing that silently reads as *no refs*
            makes every artifact look stale, which is the one direction this
            script must never fail in.

    Returns:
        Standard output, with the trailing newline removed.

    Raises:
        SweepError: If git is missing, or it failed and ``check`` is set.
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
    if completed.returncode != 0:
        if check:
            raise SweepError(f"git {' '.join(args)} in {repo} failed: {completed.stderr.strip()}")
        return ""
    return completed.stdout.rstrip("\n")


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


def direct_refs(repo: Path, *extra: str) -> list[str]:
    """List the branch refs, excluding symbolic ones.

    ``refs/remotes/origin/HEAD`` is the one that matters: ``git clone`` creates it
    as a symbolic ref to the default branch, so it *contains* every commit on
    ``main`` under a name that is not ``main``. Counted as an ordinary ref it
    makes every merged artifact look like one a live branch still holds, and the
    sweep retires nothing.

    Args:
        repo: The repository root.
        *extra: Further arguments for ``for-each-ref``, e.g. ``--contains <sha>``.

    Returns:
        The names of the non-symbolic branch refs.

    Raises:
        SweepError: If git cannot answer. "No refs" and "git failed" must never
            be the same result here.
    """
    listing = _git(
        "for-each-ref",
        "--format=%(refname)\t%(symref)",
        *extra,
        *_BRANCH_NAMESPACES,
        repo=repo,
        check=True,
    )
    names: list[str] = []
    for line in listing.splitlines():
        refname, _, symref = line.partition("\t")
        if refname and not symref:
            names.append(refname)
    return names


class Refs:
    """What the repository's refs currently hold, read once per sweep."""

    def __init__(self, repo: Path) -> None:
        """Read the ref state.

        Args:
            repo: The repository root.
        """
        self.repo = repo
        self.branches: set[str] = set()
        for line in direct_refs(repo):
            if line.startswith("refs/heads/"):
                self.branches.add(line.removeprefix("refs/heads/"))
            elif line.startswith("refs/remotes/"):
                # `refs/remotes/origin/feature/x` -> `feature/x`: the remote name
                # is one component and the rest is the branch as an artifact
                # records it.
                rest = line.removeprefix("refs/remotes/").split("/", 1)
                if len(rest) == 2:  # noqa: PLR2004  # a remote name and a branch
                    self.branches.add(rest[1])
        # Tags are read as POINTS-AT, never as contains. `--contains` over
        # `refs/tags` asks "is this commit an ancestor of a tag?", so one release
        # tag on `main` would answer yes for every artifact older than it and the
        # sweep would retire nothing — the same shape as the `origin/HEAD` hole,
        # from the opposite direction. What a tag says is that *this* commit was
        # marked, so only the commit it points at is retained.
        #
        # `%(*objectname)` is the peeled target, non-empty only for an annotated
        # tag; both oids go in, since the tag object's own id can never collide
        # with a recorded commit and costs nothing to carry.
        self.tagged: set[str] = set()
        tags = _git(
            "for-each-ref",
            "--format=%(objectname) %(*objectname)",
            "refs/tags",
            repo=repo,
            check=True,
        )
        for line in tags.splitlines():
            self.tagged.update(line.split())
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
            True when at least one such branch does, or when a tag points
            directly at the commit.
        """
        if not _git_ok("cat-file", "-e", f"{sha}^{{commit}}", repo=self.repo):
            return False
        if sha in self.tagged:
            return True
        holders = direct_refs(self.repo, "--contains", sha)
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

    state, detail = _state(branch, sha, refs)
    return Verdict(artifact, state, detail, key)


def _state(branch: str, sha: str, refs: Refs) -> tuple[str, str]:
    """Decide one artifact's state from what the refs hold.

    Args:
        branch: The recorded branch, or the empty string.
        sha: The recorded commit, or the empty string.
        refs: The ref state.

    Returns:
        The state and the one-phrase reason for it.
    """
    if not branch and not sha:
        return "unreadable", "no branch or sha in the provenance line"
    if branch and refs.has_branch(branch):
        return "live", f"branch {branch} still exists"
    if sha and refs.held_by_a_ref(sha):
        return "live", f"{sha[:12]} is held by a ref"
    if sha and refs.is_merged(sha):
        return "merged", f"{sha[:12]} is on {refs.default}"
    if not _SHA.fullmatch(sha):
        # No commit to check, or a field that is not one — either way the
        # question "is this content still reachable?" was never actually asked,
        # and an artifact that cannot be classified is one this keeps.
        #
        # A WELL-FORMED sha that no ref holds is a different answer and stays
        # `stale`, deliberately. Its object may be absent from this clone (a
        # rebase-merged lane's commit, once `git gc` has run) — but "absent from
        # the object database AND held by no ref" is *more* certainly dead than
        # merely unreferenced, not less. Retaining those would make an old clone,
        # the one with most to sweep, sweep nothing at all.
        missing = "no sha to check" if not sha else f"sha {sha!r} is not a commit id"
        return "unreadable", f"branch {branch} is gone, but {missing}" if branch else missing
    return "stale", f"{sha[:12]} is in no ref"


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
    # Checked BEFORE anything is classified. Outside a work tree there are no
    # refs to read, and "no refs" is indistinguishable from "every branch is
    # gone" — so an unverified `--repo` would sweep every artifact it could
    # parse. The classifier is only fail-closed if it is asked about a repository.
    if _git("rev-parse", "--is-inside-work-tree", repo=repo) != "true":
        raise SweepError(
            f"{repo} is not inside a git work tree. This classifies artifacts by\n"
            f"what the refs still hold, so with no refs to read every artifact would\n"
            f"look stale — refusing rather than sweeping the lot."
        )
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
