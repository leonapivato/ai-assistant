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
recoverable and a mistaken classification then costs nothing. **Nothing under the
archive is ever replaced**, which is what makes that sentence true: a rename
replaces its destination silently, so an artifact whose name is already archived
lands beside that copy as ``<name>-2.md`` rather than over it, and the sweep says
so (issue #1410).

Both actions have the same effect on the two mechanisms above: ``.review/*.md``
is not recursive, so an archived artifact is as invisible to them as a deleted
one.

**Disposition snapshots follow their artifact, but only when nothing else needs
them.** ``.review/dispositions/<loop>-<persona>-<tree>.md`` is what ``ship``
publishes beside a verdict (ADR-0025 §4), and it fails closed on a snapshot that
is missing *or* ambiguous. A snapshot is swept only when no retained artifact
carries its ``(loop, persona, tree)``, so a sweep can never strand a retained
artifact without its evidence.

**A parted round's part messages follow their artifact, always** (issue #3184).
``.review/parts/<stem>/`` holds the part turns' captured messages beside the
artifact ``<stem>.md`` the round records (ADR-0331 §5:11). That directory is
swept exactly when its artifact is, and kept exactly when its artifact is — for
whatever reason it is kept, ``unreadable`` included — so a sweep can never leave
a retained verdict without the messages it was given over. Archived, it lands
under ``archive/parts/`` at the archived artifact's own stem, numbered with it
when the artifact is, so the pair is still a pair in the archive.

**A parts directory with no artifact of its stem is swept too, once it has sat
unchanged for an hour.** Nothing reads it: ``ship`` and the round aggregate glob
``.review/*.md``, and its artifact is already gone — swept by a sweep that
predates this rule, deleted, or withdrawn for a re-review that never finished
(``codex-review.sh`` withdraws the old artifact before it swaps the parts). It
carries no provenance of its own, so the ref classification above has nothing
to ask about, and the only thing that tells such remains apart from a round's
install *in flight* is time. ``codex-review.sh`` installs the parts first and
renames the artifact into place a few filesystem operations later, so for that
instant a live round's parts are an orphan here; the hour is what keeps a sweep
that lands in the instant from archiving them out from under the verdict about
to appear beside them. The same rule covers a ``<stem>.partial.<pid>`` staging
directory an interrupted install stranded. Archived, an orphan lands under
``archive/orphaned-parts/``, never ``archive/parts/``: nothing records which
archived recording of its stem it belonged to, so it is not filed beside one.
Nothing that is not a plain directory is touched: what this cannot classify, it
keeps.

**A parts directory is acted on only once it is proved to be the one
classified.** A round can install parts at a stem between the classification
and the act, so the sweep first renames the directory under a name no round
installs at, then compares it with what it classified, and puts back — and
stops — on a mismatch. And a pair is archived as a pair or not at all: when the
parts cannot follow their artifact, the artifact is put back too, so no later
sweep has to guess which archived recording a stranded directory belonged to.
Two sweeps never interleave: one that would change anything holds an ``flock``
on ``.review/.sweep.lock`` from classifying to acting, and a second is refused.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence

#: The review directory, relative to the repository root.
REVIEW_DIR = ".review"
#: Where an archived artifact goes. Below `.review/`, which `.gitignore` already
#: covers wholesale, so this needs no ignore entry of its own.
ARCHIVE_DIR = "archive"
#: The disposition snapshots `ship` publishes beside a verdict (ADR-0025 §4).
DISPOSITIONS_DIR = "dispositions"
#: A parted round's part messages, one directory per artifact stem (ADR-0331 §5:11).
PARTS_DIR = "parts"
#: Where a parts directory with no artifact is archived: apart from
#: `archive/parts/`, whose names pair a directory with an archived artifact, since
#: nothing records which archived recording an orphan belonged to.
ORPHANS_DIR = "orphaned-parts"
#: How long a parts directory with no artifact must sit unchanged before it is
#: swept: far longer than the instant between `codex-review.sh` installing a
#: round's parts and renaming its artifact into place.
ORPHAN_GRACE_SECONDS = 3600
#: The lock a sweep that changes anything holds for its whole run.
SWEEP_LOCK = ".sweep.lock"
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


class PartsVerdict(NamedTuple):
    """One parts directory's classification.

    Attributes:
        path: The entry under ``.review/parts/``.
        swept: Whether the sweep acts on it.
        state: ``paired`` (it follows its artifact), ``orphan`` (no artifact of
            its stem, unchanged for the grace period), ``recent`` (no artifact,
            but changed within the grace period) or ``unreadable`` (not a plain
            directory).
        detail: Why, in one phrase.
        artifact: The artifact it follows, or ``None`` when it has none.
        identity: The directory's ``(st_dev, st_ino)`` when it was classified,
            which is what the sweep later proves it is acting on; ``None`` for
            an entry that is not a plain directory.
    """

    path: Path
    swept: bool
    state: str
    detail: str
    artifact: Path | None
    identity: tuple[int, int] | None


def classify_parts(review: Path, verdicts: Iterable[Verdict], now: float) -> list[PartsVerdict]:
    """Classify every entry under ``.review/parts/`` against the artifact verdicts.

    Args:
        review: The review directory.
        verdicts: Every artifact's classification.
        now: The current time, as a POSIX timestamp, the grace period is read
            against.

    Returns:
        One verdict per entry, sorted by name. Empty when there is no plain
        ``parts`` directory to read — a symbolic link there is left alone, since
        sweeping through it would move or delete what lies outside the review
        directory.
    """
    root = review / PARTS_DIR
    if root.is_symlink() or not root.is_dir():
        return []
    by_name = {v.path.name: v for v in verdicts}
    found: list[PartsVerdict] = []
    for entry in sorted(root.iterdir()):
        artifact = review / f"{entry.name}.md"
        verdict = by_name.get(artifact.name)
        try:
            status = entry.lstat()
        except OSError as exc:
            found.append(PartsVerdict(entry, False, "unreadable", str(exc), None, None))
            continue
        if not stat.S_ISDIR(status.st_mode):
            found.append(PartsVerdict(entry, False, "unreadable", "not a directory", None, None))
            continue
        identity = (status.st_dev, status.st_ino)
        if verdict is not None:
            swept = verdict.state in SWEEPABLE
            detail = f"its artifact is {verdict.state}"
            found.append(PartsVerdict(entry, swept, "paired", detail, verdict.path, identity))
        elif os.path.lexists(artifact):
            # An artifact of the stem that was never classified is not one this
            # can call gone.
            detail = f"{artifact.name} exists but was not classified"
            found.append(PartsVerdict(entry, False, "unreadable", detail, None, identity))
        # A modification time in the future reads as a negative age, and so as
        # recent: a skewed clock costs a later sweep, never this round.
        elif now - status.st_mtime < ORPHAN_GRACE_SECONDS:
            detail = "no artifact, but changed within the hour; a round may be installing it"
            found.append(PartsVerdict(entry, False, "recent", detail, None, identity))
        else:
            detail = f"no {artifact.name}, and unchanged for over an hour"
            found.append(PartsVerdict(entry, True, "orphan", detail, None, identity))
    return found


def archive_plan(
    paths: Sequence[Path], review: Path, companions: Mapping[Path, Path] | None = None
) -> list[tuple[Path, Path]]:
    """Pair each swept file with the name it lands under in the archive.

    The layout is mirrored, so a swept disposition snapshot cannot collide with a
    swept artifact of one name — but that says nothing about the *same* relative
    name being archived twice, which is what the same loop reviewing the same tree
    against the same base again after an earlier sweep produces. A rename replaces
    its destination silently, so the older copy would simply be gone, falsifying
    the reason archiving is the default at all (issue #1410).

    So a name already taken is never a destination: the newcomer is numbered and
    lands beside it. Decided for every file before any of them moves, the way this
    script decides everything else — a plan that is wrong is then wrong before it
    has changed anything.

    An artifact with a parts directory takes the first number free for *both*:
    the directory lands at ``archive/parts/<the artifact's archived stem>``, so a
    numbered artifact keeps its own messages beside it rather than an earlier
    recording's (issue #3184).

    Args:
        paths: The files being swept, each under ``review``, and then any parts
            directory being swept on its own — an orphan, which lands under
            ``archive/orphaned-parts/`` rather than beside any archived artifact.
        review: The review directory.
        companions: Each swept artifact's parts directory, keyed on the artifact.

    Returns:
        One ``(source, destination)`` pair per path, in the order given, each
        artifact's companion directly after it — so the two are acted on as one
        step, and nothing else can fail between them.
    """
    archive = review / ARCHIVE_DIR
    companions = companions or {}
    taken: set[Path] = set()

    def free(destination: Path) -> bool:
        # `taken` as well as the filesystem: a numbered name can collide with
        # another file of *this* sweep — `a.md` becoming `a-2.md` while
        # `.review/a-2.md` is itself on its way to `archive/a-2.md`.
        return not (destination in taken or destination.is_symlink() or destination.exists())

    plan: list[tuple[Path, Path]] = []
    for path in paths:
        destination = archive / path.relative_to(review)
        if path.parent == review / PARTS_DIR:
            # A parts directory swept on its own is an orphan; see ORPHANS_DIR.
            destination = archive / ORPHANS_DIR / path.name
        stem, suffix = destination.stem, destination.suffix
        companion = companions.get(path)
        ordinal = 1
        while not free(destination) or (
            companion is not None and not free(archive / PARTS_DIR / destination.stem)
        ):
            ordinal += 1
            destination = destination.with_name(f"{stem}-{ordinal}{suffix}")
        taken.add(destination)
        plan.append((path, destination))
        if companion is not None:
            beside = archive / PARTS_DIR / destination.stem
            taken.add(beside)
            plan.append((companion, beside))
    return plan


#: The prefix of the name a parts directory is held under while it is swept: a
#: name `codex-review.sh` never installs at, so no round can collide with it.
_CLAIM_PREFIX = ".sweeping-"


def _archive_file(path: Path, destination: Path) -> None:
    """Move one file to a name nothing holds, never replacing anything.

    Args:
        path: The file.
        destination: Where it goes; its parent exists.

    Raises:
        OSError: If the name is taken or the move fails, with nothing left
            half-done.
        NotImplementedError: Where ``link`` cannot decline to follow a symbolic
            link.
    """
    # `link` then `unlink`, not `rename`: a rename replaces whatever is at the
    # destination, and not replacing is the whole point. `link` fails with EEXIST
    # instead, so a name that appeared since the plan was made costs this sweep
    # rather than that file.
    #
    # `follow_symlinks=False` because `link` otherwise links what a symbolic link
    # *points at*: an artifact that is a link would be archived as a hard link to
    # its target and the link itself deleted, which is neither the file that was
    # swept nor recoverable in the sense the default rests on. A rename moved the
    # link itself, and so does this.
    os.link(path, destination, follow_symlinks=False)
    try:
        path.unlink()
    except OSError:
        # The link landed and the source did not go. Left alone, the archive would
        # hold a copy of a file that was never swept and the next sweep would
        # number a second one beside it — two copies of one artifact, from a move
        # that failed. So undo the half of it that succeeded, and only while the
        # destination is still the link just made.
        with contextlib.suppress(OSError):
            if os.path.samestat(os.lstat(path), os.lstat(destination)):
                destination.unlink()
        raise


def _move_directory(source: Path, destination: Path) -> None:
    """Move a directory to a name nothing holds, never replacing anything.

    A directory cannot be hard-linked, and ``rename`` onto a directory name
    silently replaces one that is empty. So the destination is *made* first —
    ``mkdir`` fails if anything holds the name, which reserves it — and the
    rename then replaces only that empty directory, which this call just
    created. Anything that lands in it meanwhile makes the rename fail rather
    than be replaced.

    Args:
        source: The directory to move.
        destination: Where it goes; its parent exists.

    Raises:
        OSError: If the name is taken or the move fails. The reservation is
            removed again on a failed move, while it is still empty.
    """
    destination.mkdir()
    try:
        source.rename(destination)
    except OSError:
        with contextlib.suppress(OSError):
            destination.rmdir()
        raise


def _claim(part: PartsVerdict) -> Path | None:
    """Take a parts directory out of a round's reach, and prove it is the one classified.

    Classifying and acting are two moments, and a round can install a parts
    directory between them — ``codex-review.sh`` replaces the directory at an
    artifact's stem and then renames the artifact into place. Acting on the
    *name* would then move or delete that round's messages from under the
    verdict landing beside them. So the directory is first renamed under a name
    no round installs at, and only then compared with what was classified: once
    it is held there, nothing a round does can change which directory it is.

    The identity is the device and inode, and the comparison cannot be fooled by
    the old directory's inode being reused for the new one: a round copies its
    messages into place *before* it removes the directory it replaces, so the
    new one is allocated while the old one still holds its number.

    Args:
        part: The parts directory, as classified.

    Returns:
        Where it is now held, or ``None`` when it is already gone — a round
        withdrew it, or another sweep took it — and there is nothing to act on.

    Raises:
        SweepError: If what was there is not what was classified. It is put back
            first, so the round that installed it is undisturbed.
        OSError: If the claim or the putting back fails.
    """
    held = part.path.with_name(f"{_CLAIM_PREFIX}{os.getpid()}-{part.path.name}")
    try:
        _move_directory(part.path, held)
    except FileNotFoundError:
        return None
    try:
        status = held.lstat()
    except OSError:
        # Unproved is not proved: put it back at its own name, so the caller can
        # put its artifact back beside it, and fail as any other OSError here.
        _give_back(part, held)
        raise
    if (status.st_dev, status.st_ino) == part.identity:
        return held
    _give_back(part, held)
    raise SweepError(
        f"{PARTS_DIR}/{part.path.name}/ changed after it was classified — a review round "
        f"installed it meanwhile — so it was left where it is. Run the sweep again."
    )


def _give_back(part: PartsVerdict, held: Path) -> None:
    """Return a claimed parts directory to the name it was claimed from.

    Args:
        part: The parts directory, as classified.
        held: Where :func:`_claim` holds it.

    Raises:
        SweepError: If it cannot be returned, naming where it is.
    """
    try:
        _move_directory(held, part.path)
    except OSError as exc:
        raise SweepError(
            f"{PARTS_DIR}/{part.path.name}/ could not be put back after it was claimed: it "
            f"is at {held}. Move it back to {part.path} by hand. ({exc})"
        ) from exc


def _act(
    paths: Sequence[Path],
    plan: Sequence[tuple[Path, Path]],
    *,
    delete: bool,
    dry_run: bool,
    parts: Sequence[PartsVerdict] = (),
) -> None:
    """Archive or delete the swept files and parts directories.

    A swept artifact and its parts directory are one step: the directory comes
    directly after its artifact in both ``paths`` and ``plan``. When archiving,
    a directory that cannot follow its artifact — the claim, the destination or
    the move failing — puts the artifact back, so a failure never leaves the
    pair split across the archive under a number only this sweep knew: the next
    sweep finds both where they were and plans them together again. When
    deleting, a split pair is an artifact gone and an orphan the next sweep
    deletes, which loses nothing that pairing protects.

    Args:
        paths: The files and directories to act on. Deletion needs nothing else;
            it has no destinations to reason about.
        plan: Where each of those lands under the archive, from
            :func:`archive_plan`. Empty when deleting, which computes none.
        delete: Delete rather than archive.
        dry_run: Decide everything and change nothing.
        parts: The swept parts directories' classifications. A directory in
            ``paths`` or ``plan`` is acted on only through its classification,
            and only once :func:`_claim` has proved it is still that directory.

    Raises:
        SweepError: If a file cannot be moved or removed — including a filesystem
            that cannot hard-link, and a platform whose ``link`` cannot decline to
            follow a symbolic link. Both fail the sweep rather than falling back
            to something that replaces or rewrites, which is the direction every
            other refusal here takes: what cannot be done safely is not done.
    """
    if dry_run:
        return
    classified = {p.path: p for p in parts}
    try:
        if delete:
            _delete(paths, classified)
        else:
            _archive(plan, classified)
    except (OSError, NotImplementedError) as exc:
        # `NotImplementedError` is what `link` raises where it cannot decline to
        # follow a symbolic link. It is not an `OSError`, and an uncaught one
        # would be a traceback where every other failure here is a refusal.
        raise SweepError(f"could not sweep the review directory: {exc}") from exc


def _delete(paths: Sequence[Path], classified: Mapping[Path, PartsVerdict]) -> None:
    """Delete the swept files and, once claimed, the swept parts directories.

    Args:
        paths: What to delete.
        classified: The parts directories among them, by path.
    """
    for path in paths:
        part = classified.get(path)
        if part is None:
            path.unlink()
        elif (held := _claim(part)) is not None:
            shutil.rmtree(held)


def _archive(plan: Sequence[tuple[Path, Path]], classified: Mapping[Path, PartsVerdict]) -> None:
    """Archive the swept files and, once claimed, the swept parts directories.

    Args:
        plan: Each path with where it lands, each artifact's companion directly
            after it.
        classified: The parts directories among them, by path.

    Raises:
        SweepError: If a directory changed after it was classified.
    """
    archived: dict[Path, Path] = {}
    for path, destination in plan:
        part = classified.get(path)
        if part is None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            _archive_file(path, destination)
            archived[path] = destination
            continue
        held: Path | None = None
        try:
            held = _claim(part)
            if held is None:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            _move_directory(held, destination)
        except OSError:
            # A mismatch on the claim is a `SweepError` and does not come here:
            # then a round has replaced the messages, its own artifact follows,
            # and the archived one has nothing left to be paired with.
            _put_back(part, held, archived)
            raise


def _put_back(part: PartsVerdict, held: Path | None, archived: Mapping[Path, Path]) -> None:
    """Undo a pair's half-done archive: its parts to their name, its artifact back.

    Args:
        part: The parts directory that could not be archived.
        held: Where :func:`_claim` holds it, or ``None`` when it was never
            claimed and so is still at its own name.
        archived: Each file this sweep archived, with where it went.

    Raises:
        SweepError: If either cannot be put back, naming where each now is.
    """
    try:
        if held is not None:
            _move_directory(held, part.path)
        if part.artifact is not None and part.artifact in archived:
            _archive_file(archived[part.artifact], part.artifact)
    except (OSError, NotImplementedError) as exc:
        messages = held if held is not None and held.exists() else part.path
        artifact = archived.get(part.artifact) if part.artifact is not None else None
        raise SweepError(
            f"could not archive {PARTS_DIR}/{part.path.name}/ beside its artifact, nor put "
            f"the pair back: the messages are at {messages}"
            + (f" and the artifact at {artifact}" if artifact is not None else "")
            + f". ({exc})"
        ) from exc


def _report(  # noqa: PLR0913 — what was classified, what follows it, and how it was acted on
    verdicts: Sequence[Verdict],
    snapshots: Sequence[Path],
    parts: Sequence[PartsVerdict],
    renamed: Sequence[tuple[Path, Path]],
    *,
    delete: bool,
    dry_run: bool,
) -> None:
    """Print the plan or the result.

    Args:
        verdicts: Every artifact's classification.
        snapshots: The disposition snapshots being swept.
        parts: Every parts directory's classification.
        renamed: The swept paths whose archived name was already taken, each with
            the name it lands under instead. Reported rather than left to be
            found, because the numbered name is the one thing the per-file line
            above does not already say.
        delete: Whether the action is deletion.
        dry_run: Whether anything was actually done.
    """
    action = "delete" if delete else "archive"
    verb = f"would {action}" if dry_run else f"{action}d"
    for verdict in sorted(verdicts, key=lambda v: (v.state, v.path.name)):
        mark = verb if verdict.state in SWEEPABLE else "keep"
        print(f"{mark:>14}  {verdict.path.name}  [{verdict.state}] {verdict.detail}")
    for part in parts:
        mark = verb if part.swept else "keep"
        print(f"{mark:>14}  {PARTS_DIR}/{part.path.name}/  [{part.state}] {part.detail}")
    for path, destination in renamed:
        lands = "would land" if dry_run else "landed"
        shown = f"{PARTS_DIR}/{path.name}/" if path.parent.name == PARTS_DIR else path.name
        print(
            f"{'renamed':>14}  {shown}  [taken] already under the archive; "
            f"{lands} as {destination.name}"
        )
    states = ("live", "merged", "stale", "unreadable")
    counts = {state: sum(1 for v in verdicts if v.state == state) for state in states}
    print(
        f"\n{len(verdicts)} artifact(s): {counts['live']} live, {counts['merged']} merged, "
        f"{counts['stale']} stale, {counts['unreadable']} unreadable; "
        f"{len(snapshots)} disposition snapshot(s) {verb}; "
        f"{sum(1 for p in parts if p.swept)} parts director(ies) {verb}."
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
    with contextlib.nullcontext() if args.dry_run else _one_sweep_at_a_time(review):
        _sweep_review(repo, review, delete=args.delete, dry_run=args.dry_run)
    return 0


@contextlib.contextmanager
def _one_sweep_at_a_time(review: Path) -> Iterator[None]:
    """Hold the review directory's sweep lock for as long as the context lasts.

    Two sweeps interleaving is the one race the per-directory claim cannot
    settle: a directory one sweep holds under its claim name looks to another
    like an old orphan, and the second would take it out from under the first.
    So a sweep that would change anything holds this for its whole run, from
    classifying to acting, and a second is refused rather than queued. An
    ``flock`` lives on the open descriptor, so a sweep that dies releases it.

    Args:
        review: The review directory.

    Yields:
        Nothing; the lock is held until the context exits.

    Raises:
        SweepError: If another sweep holds the lock, or it cannot be taken.
    """
    path = review / SWEEP_LOCK
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o644)
    except OSError as exc:
        raise SweepError(f"could not open the sweep lock {path}: {exc}") from exc
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SweepError(
                f"another review sweep is running in this clone (it holds {path}); "
                f"run this one after it finishes."
            ) from exc
        except OSError as exc:
            raise SweepError(f"could not take the sweep lock {path}: {exc}") from exc
        yield
    finally:
        os.close(descriptor)


def _sweep_review(repo: Path, review: Path, *, delete: bool, dry_run: bool) -> None:
    """Classify the review directory and act on what is sweepable.

    Args:
        repo: The repository root.
        review: Its review directory.
        delete: Delete rather than archive.
        dry_run: Decide everything and change nothing.
    """
    refs = Refs(repo)
    verdicts = [classify(a, refs) for a in sorted(review.glob("*.md"))]
    swept = [v for v in verdicts if v.state in SWEEPABLE]
    retained = [v for v in verdicts if v.state not in SWEEPABLE]
    snapshots = snapshots_to_sweep(review, swept, retained)
    parts = classify_parts(review, verdicts, time.time())
    companions = {p.artifact: p.path for p in parts if p.swept and p.artifact is not None}
    orphans = [p.path for p in parts if p.swept and p.artifact is None]
    # `archive_plan` puts each companion directly after its artifact, which is
    # what `_act` treats as one step; the orphans, unpaired, go last.
    files = [v.path for v in swept] + snapshots
    if delete:
        plan: list[tuple[Path, Path]] = []
        sweeping = [*files, *companions.values(), *orphans]
    else:
        plan = archive_plan([*files, *orphans], review, companions)
        sweeping = [source for source, _ in plan]
    _act(sweeping, plan, delete=delete, dry_run=dry_run, parts=[p for p in parts if p.swept])
    renamed = [pair for pair in plan if pair[1].name != pair[0].name]
    _report(verdicts, snapshots, parts, renamed, delete=delete, dry_run=dry_run)


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
