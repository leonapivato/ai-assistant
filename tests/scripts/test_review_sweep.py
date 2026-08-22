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
"""

from __future__ import annotations

import sys
from pathlib import Path

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
