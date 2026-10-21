"""Tests for ``scripts/review_sweep.py`` (issue #1391).

The sweep is only as good as its classifier, and the two directions cost very
different things. Sweeping an artifact a **live** branch could still use resets
the round count ADR-0138 §1's handoff threshold is read off and can make ``ship``
demand a fresh review of content already reviewed; keeping a dead one is merely
untidy. So every test below that could go either way is written to fail if the
sweep is too eager, and "unclassifiable" is asserted to mean *kept*.

The disposition-snapshot rule gets the same treatment: ``ship`` fails closed on a
snapshot that is missing, so a snapshot shared with a retained artifact must
survive.

Archiving is the default *because* it is recoverable, so the archive itself is
held to that: the tests below sweep one name twice and assert that both copies
are still there afterwards. A rename would have replaced the first silently, and
the module's own justification for the default would have been false (#1410).
"""

from __future__ import annotations

import fcntl
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _operator_recipes import git, init_repo, load, run

_MODULE = load("review_sweep")


def _provenance(**fields: str) -> str:
    """One artifact's provenance comment, in `codex-review.sh`'s field order."""
    body = " ".join(f"{name}={value}" for name, value in fields.items())
    return f"<!-- {body} -->\n"


def _artifact(repo: Path, name: str, **fields: str) -> Path:
    """Write an artifact under ``.review/`` and return it."""
    review = repo / ".review"
    review.mkdir(exist_ok=True)
    path = review / name
    path.write_text(_provenance(**fields) + "Verdict: APPROVE\n")
    return path


def _snapshot(repo: Path, loop: str, persona: str, tree: str) -> Path:
    """Write a disposition snapshot keyed on (loop, persona, tree)."""
    directory = repo / ".review" / "dispositions"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{loop}-{persona}-{tree}.md"
    # `codex-review.sh` writes a bare `snapshot` token before the fields.
    path.write_text(f"<!-- snapshot loop_id={loop} persona={persona} tree={tree} -->\n")
    return path


def _repo(tmp_path: Path) -> Path:
    """A clone with an origin, on ``main``."""
    repo = tmp_path / "clone"
    init_repo(repo, with_origin=True)
    return repo


def _sweep(repo: Path, *args: str) -> tuple[int, str, str]:
    """Run the sweep over ``repo``."""
    result = run("review_sweep", ["--repo", str(repo), *args])
    return result.returncode, result.stdout, result.stderr


def _branch_with_commit(repo: Path, name: str) -> str:
    """Create ``name`` with one commit on it and return that commit."""
    git(repo, "switch", "-qc", name)
    (repo / f"{name.replace('/', '-')}.txt").write_text("work\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"work on {name}")
    sha = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-q", "main")
    return sha


# --------------------------------------------------------------------------- #
# Classification                                                               #
# --------------------------------------------------------------------------- #


def test_an_artifact_of_a_live_branch_is_kept(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sha = _branch_with_commit(repo, "some/lane")
    artifact = _artifact(
        repo, "a.md", persona="adversarial", branch="some/lane", sha=sha, tree="t1"
    )

    status, out, _ = _sweep(repo)

    assert status == 0, out
    assert "[live]" in out
    assert artifact.exists()


def test_an_artifact_of_a_deleted_branch_is_stale_and_archived(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sha = _branch_with_commit(repo, "gone/lane")
    git(repo, "branch", "-qD", "gone/lane")
    artifact = _artifact(
        repo, "a.md", persona="adversarial", branch="gone/lane", sha=sha, tree="t1"
    )

    status, out, _ = _sweep(repo)

    assert status == 0, out
    assert "[stale]" in out
    assert not artifact.exists()
    assert (repo / ".review" / "archive" / "a.md").exists()


def test_an_artifact_whose_commit_reached_main_is_merged(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "g.txt").write_text("landed\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "landed")
    git(repo, "push", "-q", "origin", "main")
    sha = git(repo, "rev-parse", "HEAD")
    _artifact(repo, "a.md", persona="adversarial", branch="landed/lane", sha=sha, tree="t1")

    status, out, _ = _sweep(repo)

    assert status == 0, out
    assert "[merged]" in out
    assert (repo / ".review" / "archive" / "a.md").exists()


def test_origin_head_does_not_keep_a_merged_artifact_alive(tmp_path: Path) -> None:
    # `git clone` creates `refs/remotes/origin/HEAD` as a symbolic ref to the
    # default branch, so it *contains* every commit on main under a name that is
    # not main. Counted as an ordinary holder, it makes every merged artifact
    # look live and the sweep retires nothing at all.
    repo = _repo(tmp_path)
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    sha = git(repo, "rev-parse", "HEAD")
    _artifact(repo, "a.md", persona="adversarial", branch="landed/lane", sha=sha, tree="t1")

    status, out, _ = _sweep(repo)

    assert status == 0, out
    assert "[merged]" in out


def test_a_live_branch_wins_over_a_dead_looking_commit(tmp_path: Path) -> None:
    # The branch name is the aggregate's scope key, so an artifact naming a branch
    # that still exists is live whatever its recorded commit says.
    repo = _repo(tmp_path)
    _branch_with_commit(repo, "some/lane")
    _artifact(repo, "a.md", persona="adversarial", branch="some/lane", sha="0" * 40, tree="t1")

    status, out, _ = _sweep(repo)

    assert status == 0, out
    assert "[live]" in out


def test_a_commit_held_by_a_ref_under_another_name_is_live(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sha = _branch_with_commit(repo, "old/name")
    git(repo, "branch", "-qm", "old/name", "new/name")
    _artifact(repo, "a.md", persona="adversarial", branch="old/name", sha=sha, tree="t1")

    status, out, _ = _sweep(repo)

    assert status == 0, out
    assert "is held by a ref" in out


def test_a_commit_held_only_by_a_tag_is_live(tmp_path: Path) -> None:
    # "Some ref still holds it" has to mean any ref, not any branch: a tagged
    # commit is retained whatever became of the branch that carried it.
    repo = _repo(tmp_path)
    sha = _branch_with_commit(repo, "gone/lane")
    git(repo, "tag", "release-x", sha)
    git(repo, "branch", "-qD", "gone/lane")
    artifact = _artifact(
        repo, "a.md", persona="adversarial", branch="gone/lane", sha=sha, tree="t1"
    )

    status, out, _ = _sweep(repo)

    assert status == 0, out
    assert "is held by a ref" in out
    assert artifact.exists()


def test_a_later_release_tag_does_not_retain_every_older_artifact(tmp_path: Path) -> None:
    # `--contains` over refs/tags asks "is this an ancestor of a tag?", so one
    # release tag on main would answer yes for every artifact older than it and
    # the sweep would retire nothing — the `origin/HEAD` hole from the other
    # direction. A tag retains only the commit it points AT.
    repo = _repo(tmp_path)
    old_sha = _branch_with_commit(repo, "gone/lane")
    git(repo, "branch", "-qD", "gone/lane")
    git(repo, "merge", "-q", "--ff-only", old_sha)
    git(repo, "push", "-q", "origin", "main")
    (repo / "later.txt").write_text("after the artifact\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "later release")
    git(repo, "tag", "-a", "v1.0", "-m", "release")
    git(repo, "push", "-q", "origin", "main")
    _artifact(repo, "a.md", persona="adversarial", branch="gone/lane", sha=old_sha, tree="t1")

    status, out, _ = _sweep(repo, "--dry-run")

    assert status == 0, out
    assert "[merged]" in out
    assert "[live]" not in out


def test_an_annotated_tag_pointing_at_the_commit_still_retains_it(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sha = _branch_with_commit(repo, "gone/lane")
    git(repo, "tag", "-a", "kept", "-m", "keep this one", sha)
    git(repo, "branch", "-qD", "gone/lane")
    _artifact(repo, "a.md", persona="adversarial", branch="gone/lane", sha=sha, tree="t1")

    status, out, _ = _sweep(repo, "--dry-run")

    assert status == 0, out
    assert "is held by a ref" in out


def test_a_tag_is_not_read_as_a_branch_name(tmp_path: Path) -> None:
    # Tags count for containment and not for the `branch=` lookup, so an artifact
    # naming a gone branch that happens to share a tag's name is still stale.
    repo = _repo(tmp_path)
    git(repo, "tag", "gone/lane")
    _artifact(repo, "a.md", persona="adversarial", branch="gone/lane", sha="0" * 40, tree="t1")

    status, out, _ = _sweep(repo, "--dry-run")

    assert status == 0, out
    assert "[stale]" in out


def test_an_artifact_with_no_readable_provenance_is_kept(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    review = repo / ".review"
    review.mkdir()
    artifact = review / "a.md"
    artifact.write_text("no provenance line at all\n")

    status, out, _ = _sweep(repo)

    assert status == 0, out
    assert "[unreadable]" in out
    assert artifact.exists()


def test_a_gone_branch_with_no_recorded_commit_is_kept(tmp_path: Path) -> None:
    # The branch is gone, but with no sha there is no way to ask whether the
    # content survives under another branch name — so it is unclassifiable, and
    # unclassifiable means kept. `--delete` must not destroy it either.
    repo = _repo(tmp_path)
    artifact = _artifact(repo, "a.md", persona="adversarial", branch="gone/lane", tree="t1")

    status, out, _ = _sweep(repo, "--delete")

    assert status == 0, out
    assert "[unreadable]" in out
    assert "no sha to check" in out
    assert artifact.exists()


def test_a_malformed_sha_is_kept_rather_than_guessed_at(tmp_path: Path) -> None:
    # `abc!junk` is not a commit id, so neither git question was actually asked —
    # and `--delete` must not destroy what was never classified.
    repo = _repo(tmp_path)
    artifact = _artifact(
        repo, "a.md", persona="adversarial", branch="gone/lane", sha="abc!junk", tree="t1"
    )

    status, out, _ = _sweep(repo, "--delete")

    assert status == 0, out
    assert "[unreadable]" in out
    assert "is not a commit id" in out
    assert artifact.exists()


def test_a_well_formed_sha_no_ref_holds_is_still_stale(tmp_path: Path) -> None:
    # The other half of the same rule, and the one that keeps the sweep useful:
    # a 40-hex commit absent from every ref is dead whether or not its object
    # still sits in this clone. Retaining those would make an old clone — the one
    # with most to sweep — sweep nothing.
    repo = _repo(tmp_path)
    _artifact(repo, "a.md", persona="adversarial", branch="gone/lane", sha="0" * 40, tree="t1")

    status, out, _ = _sweep(repo, "--dry-run")

    assert status == 0, out
    assert "[stale]" in out


def test_a_legacy_named_artifact_is_classified_from_its_header(tmp_path: Path) -> None:
    # The old name is `<sha>-<persona>.md` and the new one ends in a *tree* hash,
    # so nothing here may parse the filename.
    repo = _repo(tmp_path)
    sha = _branch_with_commit(repo, "gone/lane")
    git(repo, "branch", "-qD", "gone/lane")
    _artifact(
        repo, f"{sha}-adversarial.md", persona="adversarial", branch="gone/lane", sha=sha, tree="t1"
    )

    status, out, _ = _sweep(repo)

    assert status == 0, out
    assert "[stale]" in out


# --------------------------------------------------------------------------- #
# What the two actions do                                                      #
# --------------------------------------------------------------------------- #


def test_delete_removes_rather_than_archives(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _artifact(repo, "a.md", persona="adversarial", branch="gone/lane", sha="0" * 40, tree="t1")

    status, out, _ = _sweep(repo, "--delete")

    assert status == 0, out
    assert "deleted" in out
    assert not (repo / ".review" / "a.md").exists()
    assert not (repo / ".review" / "archive").exists()


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    artifact = _artifact(
        repo, "a.md", persona="adversarial", branch="gone/lane", sha="0" * 40, tree="t1"
    )

    status, out, _ = _sweep(repo, "--dry-run")

    assert status == 0, out
    assert "would archive" in out
    assert artifact.exists()


def test_an_archived_artifact_is_invisible_to_the_ship_glob(tmp_path: Path) -> None:
    # `ship.sh` and `codex-review.sh` both read `.review/*.md`, which is not
    # recursive — that is what makes archiving as effective as deleting.
    repo = _repo(tmp_path)
    _artifact(repo, "a.md", persona="adversarial", branch="gone/lane", sha="0" * 40, tree="t1")

    _sweep(repo)

    assert list((repo / ".review").glob("*.md")) == []
    assert (repo / ".review" / "archive" / "a.md").exists()


def test_a_name_already_in_the_archive_is_never_replaced(tmp_path: Path) -> None:
    # The same loop reviewing the same tree against the same base again after an
    # earlier sweep archives one name twice. `rename` replaces its destination, so
    # the first copy would be gone — and archiving is the default *because* a
    # local move is recoverable.
    repo = _repo(tmp_path)
    _artifact(repo, "a.md", persona="adversarial", branch="gone/lane", sha="0" * 40, tree="first")
    _sweep(repo)
    _artifact(repo, "a.md", persona="adversarial", branch="gone/lane", sha="0" * 40, tree="second")

    status, out, _ = _sweep(repo)

    archive = repo / ".review" / "archive"
    assert status == 0, out
    assert "tree=first" in (archive / "a.md").read_text()
    assert "tree=second" in (archive / "a-2.md").read_text()
    assert "landed as a-2.md" in out


def test_a_numbered_name_does_not_collide_with_another_file_of_the_same_sweep(
    tmp_path: Path,
) -> None:
    # `a.md` becoming `a-2.md` while `.review/a-2.md` is itself on its way to
    # `archive/a-2.md`: the destinations are checked against each other as well as
    # against the filesystem, or the fix would reintroduce the bug one step over.
    repo = _repo(tmp_path)
    archive = repo / ".review" / "archive"
    archive.mkdir(parents=True)
    (archive / "a.md").write_text("already archived\n")
    _artifact(repo, "a.md", persona="adversarial", branch="gone/lane", sha="0" * 40, tree="plain")
    _artifact(
        repo, "a-2.md", persona="adversarial", branch="gone/lane", sha="0" * 40, tree="numbered"
    )

    status, out, _ = _sweep(repo)

    assert status == 0, out
    assert (archive / "a.md").read_text() == "already archived\n"
    assert "tree=numbered" in (archive / "a-2.md").read_text()
    assert "tree=plain" in (archive / "a-3.md").read_text()


def test_a_symlinked_artifact_is_archived_as_the_link_it_is(tmp_path: Path) -> None:
    # `link` follows a symbolic link by default, so archiving one would put a hard
    # link to whatever it points at under the archive and delete the link — the
    # swept file would not be what was archived, and an external file would be
    # held open by the archive. A rename moved the link itself; so does this.
    repo = _repo(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text(_provenance(persona="adversarial", branch="gone/lane", sha="0" * 40))
    (repo / ".review").mkdir()
    (repo / ".review" / "a.md").symlink_to(outside)

    status, out, _ = _sweep(repo)

    archived = repo / ".review" / "archive" / "a.md"
    assert status == 0, out
    assert archived.is_symlink()
    assert archived.readlink() == outside
    assert not (repo / ".review" / "a.md").is_symlink()
    assert outside.exists()


def test_a_source_that_cannot_be_removed_leaves_no_half_archived_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Linking and then failing to remove the source would leave the archive
    # holding a copy of a file that was never swept, and the next sweep would
    # number a second one beside it: two copies from one failed move.
    repo = _repo(tmp_path)
    artifact = _artifact(
        repo, "a.md", persona="adversarial", branch="gone/lane", sha="0" * 40, tree="t1"
    )
    review = repo / ".review"
    plan = _MODULE.archive_plan([artifact], review)
    removed = Path.unlink

    def refuse(self: Path, missing_ok: bool = False) -> None:
        if self == artifact:
            raise PermissionError(13, "Permission denied", str(self))
        removed(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", refuse)

    with pytest.raises(_MODULE.SweepError, match="could not sweep"):
        _MODULE._act([artifact], plan, delete=False, dry_run=False)
    monkeypatch.undo()

    assert artifact.exists()
    assert not (review / "archive" / "a.md").exists()


def test_dry_run_says_which_name_it_would_land_under(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _artifact(repo, "a.md", persona="adversarial", branch="gone/lane", sha="0" * 40, tree="first")
    _sweep(repo)
    artifact = _artifact(
        repo, "a.md", persona="adversarial", branch="gone/lane", sha="0" * 40, tree="second"
    )

    status, out, _ = _sweep(repo, "--dry-run")

    assert status == 0, out
    assert "would land as a-2.md" in out
    assert artifact.exists()
    assert not (repo / ".review" / "archive" / "a-2.md").exists()


def test_a_missing_review_directory_is_a_refusal_not_a_crash(tmp_path: Path) -> None:
    status, _, err = _sweep(_repo(tmp_path))

    assert status == 1
    assert "nothing to sweep" in err


def test_a_target_outside_a_work_tree_refuses_rather_than_sweeping_the_lot(
    tmp_path: Path,
) -> None:
    # With no refs to read, "every branch is gone" and "this is not a repository"
    # are the same answer — so an unverified --repo would archive everything it
    # could parse. The check runs before a single artifact is classified.
    plain = tmp_path / "plain"
    (plain / ".review").mkdir(parents=True)
    artifact = plain / ".review" / "a.md"
    artifact.write_text(_provenance(persona="adversarial", branch="x/y", sha="0" * 40, tree="t1"))

    status, _, err = _sweep(plain)

    assert status == 1
    assert "not inside a git work tree" in err
    assert artifact.exists()


# --------------------------------------------------------------------------- #
# Disposition snapshots (ADR-0025 §4)                                          #
# --------------------------------------------------------------------------- #


def test_a_snapshot_follows_its_only_artifact(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _artifact(
        repo,
        "a.md",
        persona="adversarial",
        branch="gone/lane",
        sha="0" * 40,
        tree="t1",
        loop_id="L1",
    )
    snapshot = _snapshot(repo, "L1", "adversarial", "t1")

    status, out, _ = _sweep(repo)

    assert status == 0, out
    assert "1 disposition snapshot(s) archived" in out
    assert not snapshot.exists()
    assert (repo / ".review" / "archive" / "dispositions" / snapshot.name).exists()


def test_a_snapshot_a_retained_artifact_still_needs_is_kept(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _branch_with_commit(repo, "live/lane")
    for name, branch in (("dead.md", "gone/lane"), ("alive.md", "live/lane")):
        _artifact(
            repo,
            name,
            persona="adversarial",
            branch=branch,
            sha="0" * 40,
            tree="t1",
            loop_id="L1",
        )
    snapshot = _snapshot(repo, "L1", "adversarial", "t1")

    status, out, _ = _sweep(repo)

    assert status == 0, out
    assert "0 disposition snapshot(s)" in out
    assert snapshot.exists()


def test_a_snapshot_of_another_loop_is_left_alone(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _artifact(
        repo,
        "a.md",
        persona="adversarial",
        branch="gone/lane",
        sha="0" * 40,
        tree="t1",
        loop_id="L1",
    )
    other = _snapshot(repo, "L2", "adversarial", "t9")

    status, out, _ = _sweep(repo)

    assert status == 0, out
    assert other.exists()


# --------------------------------------------------------------------------- #
# Parts directories (ADR-0331 §5:11, issue #3184)                              #
# --------------------------------------------------------------------------- #

#: Old enough that an orphan is past the grace period.
_AGED = _MODULE.ORPHAN_GRACE_SECONDS + 60


def _parts(repo: Path, stem: str, *, age: float = 0) -> Path:
    """Write a parted round's part messages for ``stem``, ``age`` seconds old."""
    directory = repo / ".review" / "parts" / stem
    directory.mkdir(parents=True)
    (directory / "part-0001-of-0002.md").write_text(f"part one of {stem}\n")
    (directory / "part-0002-of-0002.md").write_text(f"part two of {stem}\n")
    if age:
        stamp = time.time() - age
        os.utime(directory, (stamp, stamp))
    return directory


def _dead(repo: Path, name: str, tree: str = "t1") -> Path:
    """An artifact of a deleted branch, which the sweep classifies stale."""
    return _artifact(repo, name, persona="adversarial", branch="gone/lane", sha="0" * 40, tree=tree)


def test_an_artifact_is_swept_with_its_parts(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _dead(repo, "a.md")
    parts = _parts(repo, "a")

    status, out, _ = _sweep(repo)

    archived = repo / ".review" / "archive" / "parts" / "a"
    assert status == 0, out
    assert not parts.exists()
    assert (archived / "part-0001-of-0002.md").read_text() == "part one of a\n"
    assert (archived / "part-0002-of-0002.md").exists()
    assert "1 parts director(ies) archived" in out


def test_delete_removes_the_parts_with_their_artifact(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _dead(repo, "a.md")
    parts = _parts(repo, "a")

    status, out, _ = _sweep(repo, "--delete")

    assert status == 0, out
    assert not parts.exists()
    assert not (repo / ".review" / "archive").exists()


def test_a_kept_artifact_keeps_its_parts(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sha = _branch_with_commit(repo, "some/lane")
    artifact = _artifact(
        repo, "a.md", persona="adversarial", branch="some/lane", sha=sha, tree="t1"
    )
    parts = _parts(repo, "a")

    status, out, _ = _sweep(repo)

    assert status == 0, out
    assert artifact.exists()
    assert (parts / "part-0001-of-0002.md").exists()
    assert not (repo / ".review" / "archive" / "parts").exists()


@pytest.mark.parametrize("delete", [False, True])
def test_parts_are_never_swept_while_their_artifact_is_kept(tmp_path: Path, delete: bool) -> None:
    # However old the directory is, and for whatever reason its artifact is kept
    # — `unreadable` is kept too — the messages stay beside the verdict.
    repo = _repo(tmp_path)
    sha = _branch_with_commit(repo, "some/lane")
    _artifact(repo, "live.md", persona="adversarial", branch="some/lane", sha=sha, tree="t1")
    (repo / ".review" / "unread.md").write_text("no provenance here\n")
    live = _parts(repo, "live", age=_AGED * 100)
    unread = _parts(repo, "unread", age=_AGED * 100)

    status, out, _ = _sweep(repo, *(["--delete"] if delete else []))

    assert status == 0, out
    assert (live / "part-0001-of-0002.md").exists()
    assert (unread / "part-0001-of-0002.md").exists()
    assert "0 parts director(ies)" in out


def test_an_orphan_parts_directory_is_swept(tmp_path: Path) -> None:
    # No artifact of its stem — swept by an earlier sweep that left its parts
    # behind, or withdrawn by a re-review that never finished.
    repo = _repo(tmp_path)
    orphan = _parts(repo, "gone", age=_AGED)

    status, out, _ = _sweep(repo)

    assert status == 0, out
    assert not orphan.exists()
    assert (repo / ".review" / "archive" / "parts" / "gone" / "part-0001-of-0002.md").exists()
    assert "[orphan]" in out


def test_a_stranded_staging_directory_is_an_orphan(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    staged = _parts(repo, "a.partial.12345", age=_AGED)

    status, out, _ = _sweep(repo, "--delete")

    assert status == 0, out
    assert not staged.exists()


def test_a_recent_orphan_is_kept_as_a_possible_install_in_flight(tmp_path: Path) -> None:
    # `codex-review.sh` installs a round's parts and only then renames its
    # artifact into place, so for that instant a live round's parts have no
    # artifact beside them. A sweep landing then must not take them.
    repo = _repo(tmp_path)
    fresh = _parts(repo, "arriving")

    status, out, _ = _sweep(repo, "--delete")

    assert status == 0, out
    assert (fresh / "part-0001-of-0002.md").exists()
    assert "[recent]" in out


def test_a_parts_directory_of_a_numbered_artifact_is_numbered_with_it(tmp_path: Path) -> None:
    # The second recording of one name lands as `a-2.md`; its messages must land
    # as `parts/a-2`, not beside the first recording's under `parts/a`.
    repo = _repo(tmp_path)
    _dead(repo, "a.md", tree="first")
    _parts(repo, "a")
    _sweep(repo)
    _dead(repo, "a.md", tree="second")
    (_parts(repo, "a") / "part-0001-of-0002.md").write_text("second recording\n")

    status, out, _ = _sweep(repo)

    archive = repo / ".review" / "archive"
    assert status == 0, out
    assert "tree=second" in (archive / "a-2.md").read_text()
    assert (archive / "parts" / "a" / "part-0001-of-0002.md").read_text() == "part one of a\n"
    assert (archive / "parts" / "a-2" / "part-0001-of-0002.md").read_text() == (
        "second recording\n"
    )


def test_an_artifact_skips_a_number_its_parts_could_not_take(tmp_path: Path) -> None:
    # `archive/a.md` is free but `archive/parts/a` is not: the pair moves on to
    # the first number free for both, so the artifact never lands beside some
    # other recording's messages.
    repo = _repo(tmp_path)
    taken = repo / ".review" / "archive" / "parts" / "a"
    taken.mkdir(parents=True)
    (taken / "other.md").write_text("someone else's\n")
    _dead(repo, "a.md")
    _parts(repo, "a")

    status, out, _ = _sweep(repo)

    archive = repo / ".review" / "archive"
    assert status == 0, out
    assert not (archive / "a.md").exists()
    assert (archive / "a-2.md").exists()
    assert (archive / "parts" / "a-2" / "part-0001-of-0002.md").exists()
    assert (taken / "other.md").read_text() == "someone else's\n"
    assert not (taken / "part-0001-of-0002.md").exists()


def test_an_orphan_avoids_the_name_a_companion_of_the_same_sweep_takes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    archive = repo / ".review" / "archive"
    archive.mkdir(parents=True)
    (archive / "a.md").write_text("already archived\n")
    _dead(repo, "a.md")
    _parts(repo, "a")
    (_parts(repo, "a-2", age=_AGED) / "part-0001-of-0002.md").write_text("the orphan\n")

    status, out, _ = _sweep(repo)

    assert status == 0, out
    assert (archive / "parts" / "a-2" / "part-0001-of-0002.md").read_text() == "part one of a\n"
    assert (archive / "parts" / "a-2-2" / "part-0001-of-0002.md").read_text() == "the orphan\n"


def test_dry_run_leaves_the_parts_alone(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _dead(repo, "a.md")
    paired = _parts(repo, "a")
    orphan = _parts(repo, "gone", age=_AGED)

    status, out, _ = _sweep(repo, "--dry-run")

    assert status == 0, out
    assert paired.exists()
    assert orphan.exists()
    assert "2 parts director(ies) would archive" in out
    assert not (repo / ".review" / "archive").exists()


def test_a_symlink_under_parts_is_left_alone(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.md").write_text("not the sweep's\n")
    _dead(repo, "a.md")
    (repo / ".review" / "parts").mkdir()
    (repo / ".review" / "parts" / "a").symlink_to(outside)

    status, out, _ = _sweep(repo, "--delete")

    assert status == 0, out
    assert (repo / ".review" / "parts" / "a").is_symlink()
    assert (outside / "keep.md").exists()


def test_a_symlinked_parts_directory_is_not_swept_through(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    outside = tmp_path / "outside"
    (outside / "gone").mkdir(parents=True)
    (outside / "gone" / "keep.md").write_text("not the sweep's\n")
    old = time.time() - _AGED
    os.utime(outside / "gone", (old, old))
    _dead(repo, "a.md")
    (repo / ".review" / "parts").symlink_to(outside)

    status, out, _ = _sweep(repo, "--delete")

    assert status == 0, out
    assert (outside / "gone" / "keep.md").exists()


@pytest.mark.parametrize("delete", [False, True])
def test_parts_a_round_installs_after_classification_are_left_alone(
    tmp_path: Path, delete: bool
) -> None:
    # Classify an hour-old orphan, then let a round install its parts at that
    # stem exactly as `codex-review.sh` does — the messages staged, the old
    # directory removed, the staged one moved in, the artifact renamed into
    # place. Acting on the name would take the live round's messages.
    repo = _repo(tmp_path)
    review = repo / ".review"
    old = _parts(repo, "a", age=_AGED)
    (part,) = _MODULE.classify_parts(review, [], time.time())
    assert part.state == "orphan"
    staged = review / "parts" / "a.partial.999"
    staged.mkdir()
    (staged / "part-0001-of-0002.md").write_text("the live round's\n")
    shutil.rmtree(old)
    staged.rename(old)
    (review / "a.md").write_text("the live round's verdict\n")
    plan = [] if delete else _MODULE.archive_plan([part.path], review)

    with pytest.raises(_MODULE.SweepError, match="changed after it was classified"):
        _MODULE._act([part.path], plan, delete=delete, dry_run=False, parts=[part])

    assert (old / "part-0001-of-0002.md").read_text() == "the live round's\n"
    assert [p.name for p in (review / "parts").iterdir()] == ["a"]
    assert not (review / "archive" / "parts" / "a").exists()


@pytest.mark.parametrize("delete", [False, True])
def test_parts_gone_since_classification_are_nothing_to_sweep(tmp_path: Path, delete: bool) -> None:
    repo = _repo(tmp_path)
    review = repo / ".review"
    old = _parts(repo, "a", age=_AGED)
    (part,) = _MODULE.classify_parts(review, [], time.time())
    shutil.rmtree(old)
    plan = [] if delete else _MODULE.archive_plan([part.path], review)

    _MODULE._act([part.path], plan, delete=delete, dry_run=False, parts=[part])

    assert list((review / "parts").iterdir()) == []
    assert not (review / "archive" / "parts" / "a").exists()


def test_a_pair_whose_parts_cannot_be_archived_is_put_back_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The artifact is numbered `a-2.md` because `archive/a.md` is an earlier
    # recording. Were the artifact left archived when its parts fail to follow,
    # only this sweep would know `parts/a` belongs at `a-2`: the next would file
    # it as an orphan under `archive/parts/a`, beside the wrong recording.
    repo = _repo(tmp_path)
    archive = repo / ".review" / "archive"
    archive.mkdir(parents=True)
    (archive / "a.md").write_text("an earlier recording\n")
    artifact = _dead(repo, "a.md")
    parts = _parts(repo, "a")
    move = _MODULE._move_directory

    def refuse(source: Path, destination: Path) -> None:
        if destination.parent == archive / "parts":
            raise PermissionError(13, "Permission denied", str(destination))
        move(source, destination)

    monkeypatch.setattr(_MODULE, "_move_directory", refuse)
    assert _MODULE.main(["--repo", str(repo)]) == 1
    monkeypatch.undo()

    assert "tree=t1" in artifact.read_text()
    assert (parts / "part-0001-of-0002.md").exists()
    assert [p.name for p in (repo / ".review" / "parts").iterdir()] == ["a"]
    assert not (archive / "a-2.md").exists()

    status, out, _ = _sweep(repo)

    assert status == 0, out
    assert "tree=t1" in (archive / "a-2.md").read_text()
    assert (archive / "parts" / "a-2" / "part-0001-of-0002.md").exists()
    assert not (archive / "parts" / "a").exists()


def test_a_pair_whose_parts_cannot_be_claimed_is_put_back_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The claim is part of the pair's step too: a `parts/` the sweep cannot
    # rename in fails before any move, and the artifact must not stay archived
    # under a number its messages never learned.
    repo = _repo(tmp_path)
    archive = repo / ".review" / "archive"
    archive.mkdir(parents=True)
    (archive / "a.md").write_text("an earlier recording\n")
    artifact = _dead(repo, "a.md")
    parts = _parts(repo, "a")

    def refuse(part: object) -> Path:
        raise PermissionError(13, "Permission denied", str(parts))

    monkeypatch.setattr(_MODULE, "_claim", refuse)
    assert _MODULE.main(["--repo", str(repo)]) == 1
    monkeypatch.undo()

    assert "tree=t1" in artifact.read_text()
    assert (parts / "part-0001-of-0002.md").exists()
    assert not (archive / "a-2.md").exists()


def test_a_later_failure_strands_no_earlier_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each pair is finished before the next file is touched, so a failure on `b`
    # leaves `a` archived beside its own messages and `b` where it was.
    repo = _repo(tmp_path)
    archive = repo / ".review" / "archive"
    archive.mkdir(parents=True)
    for stem in ("a", "b"):
        (archive / f"{stem}.md").write_text("an earlier recording\n")
        _dead(repo, f"{stem}.md")
        _parts(repo, stem)
    move = _MODULE._archive_file

    def refuse(path: Path, destination: Path) -> None:
        if path.name == "b.md":
            raise PermissionError(13, "Permission denied", str(path))
        move(path, destination)

    monkeypatch.setattr(_MODULE, "_archive_file", refuse)
    assert _MODULE.main(["--repo", str(repo)]) == 1
    monkeypatch.undo()

    review = repo / ".review"
    assert (archive / "a-2.md").exists()
    assert (archive / "parts" / "a-2" / "part-0001-of-0002.md").exists()
    assert not (review / "parts" / "a").exists()
    assert (review / "b.md").exists()
    assert (review / "parts" / "b" / "part-0001-of-0002.md").exists()
    assert not (archive / "b-2.md").exists()


def test_a_second_sweep_is_refused_while_one_runs(tmp_path: Path) -> None:
    # A directory one sweep holds under its claim name looks to another like an
    # old orphan, so two sweeps of one clone must never interleave.
    repo = _repo(tmp_path)
    artifact = _dead(repo, "a.md")
    parts = _parts(repo, "a")
    with (repo / ".review" / _MODULE.SWEEP_LOCK).open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)

        status, _, err = _sweep(repo, "--delete")
        dry_status, dry_out, _ = _sweep(repo, "--dry-run")

    assert status == 1
    assert "another review sweep is running" in err
    assert artifact.exists()
    assert parts.exists()
    assert dry_status == 0, dry_out
    status, out, _ = _sweep(repo, "--delete")
    assert status == 0, out
    assert not parts.exists()


def test_a_directory_move_never_replaces_its_destination(tmp_path: Path) -> None:
    # `rename` silently replaces an empty directory at the destination; the
    # reservation `mkdir` makes is what turns a name taken since the plan into a
    # refusal instead.
    source = tmp_path / "source"
    source.mkdir()
    (source / "m.md").write_text("message\n")
    destination = tmp_path / "destination"
    destination.mkdir()

    with pytest.raises(FileExistsError):
        _MODULE._move_directory(source, destination)

    assert (source / "m.md").exists()
    assert destination.is_dir()
    assert list(destination.iterdir()) == []


def test_a_failed_directory_move_removes_its_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "destination"

    def refuse(self: Path, target: Path) -> Path:
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "rename", refuse)

    with pytest.raises(PermissionError):
        _MODULE._move_directory(source, destination)
    monkeypatch.undo()

    assert source.is_dir()
    assert not destination.exists()


# --------------------------------------------------------------------------- #
# Field parsing, matched to `ship.sh`'s rule                                    #
# --------------------------------------------------------------------------- #


def test_provenance_field_pins_the_field_name() -> None:
    line = "<!-- persona=adversarial base_sha=aaa sha=bbb tree=ccc -->"

    assert _MODULE.provenance_field("sha", line) == "bbb"
    assert _MODULE.provenance_field("base_sha", line) == "aaa"
    assert _MODULE.provenance_field("tree", line) == "ccc"


def test_provenance_field_is_empty_for_an_absent_field() -> None:
    assert _MODULE.provenance_field("loop_id", "<!-- persona=adversarial -->") == ""


def test_provenance_field_takes_the_whole_token(tmp_path: Path) -> None:
    # `[0-9a-f]*` would stop at the first non-hex byte and return something
    # well-formed for a malformed field; the value must mismatch instead.
    assert _MODULE.provenance_field("sha", "<!-- sha=abc!junk -->") == "abc!junk"
