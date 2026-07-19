"""Integration tests for the workspace-isolation scripts.

`claim-workspace.sh` / `release-workspace.sh` create branches and worktrees —
destructive, stateful operations — so they are exercised end to end against a
throwaway git repo, with the bootstrap step stubbed
(`WORKSPACE_BOOTSTRAP=true`) so no real `uv sync` runs. Every claim is a linked
worktree; the main checkout is never claimed (it stays on `master`). Covers the
failure and concurrency paths the scripts introduce (adversarial review of
PR #17, and the always-worktree simplification that followed it).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_SCRIPTS = Path(__file__).parents[2] / "scripts"
_CLAIM = _SCRIPTS / "claim-workspace.sh"
_RELEASE = _SCRIPTS / "release-workspace.sh"
_BASH = shutil.which("bash")
_GIT = shutil.which("git")


def _git(repo: Path, *args: str) -> None:
    assert _GIT is not None
    subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [_GIT, "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def _current_branch(repo: Path) -> str:
    assert _GIT is not None
    out = subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [_GIT, "-C", str(repo), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    """A one-commit repo whose default branch is master (version-independent)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/master")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "f.txt").write_text("x\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-qm", "init")
    return repo


def _run(
    script: Path,
    repo: Path,
    *args: str,
    cwd: Path | None = None,
    bootstrap: str = "true",
    force: str | None = None,
) -> subprocess.CompletedProcess[str]:
    assert _BASH is not None
    env = os.environ.copy()
    env["WORKSPACE_BOOTSTRAP"] = bootstrap
    if force is not None:
        env["FORCE"] = force
    return subprocess.run(  # noqa: S603  # resolved bash, in-repo script, test env
        [_BASH, str(script), *args],
        cwd=str(cwd or repo),
        capture_output=True,
        text=True,
        env=env,
        check=False,  # tests assert on returncode, including the failure paths
    )


def _workspace_from(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("WORKSPACE="):
            return line.removeprefix("WORKSPACE=")
    msg = f"no WORKSPACE= line in output:\n{stdout}"
    raise AssertionError(msg)


def _workspace(result: subprocess.CompletedProcess[str]) -> str:
    return _workspace_from(result.stdout)


def test_claim_from_main_checkout_creates_a_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    result = _run(_CLAIM, repo, "area/one")

    assert result.returncode == 0, result.stderr
    ws = Path(_workspace(result))
    assert ws != repo  # main checkout is never claimed
    assert ws.is_dir()
    assert ws == tmp_path / "repo-worktrees" / "area" / "one"
    assert _current_branch(repo) == "master"  # main checkout untouched


def test_claim_tags_the_branch_as_workspace_claimed(tmp_path: Path) -> None:
    """prune-workspaces.sh trusts only branches carrying this tag (PR #17 review).

    Without it, a hand-created branch that coincidentally shares a commit with
    some old closed PR would look identical to a real claim. The tag is a
    dedicated ref, not `git config` — a shared file that would serialise
    concurrent claims on its lock (see the N-way concurrency test below).
    """
    repo = _init_repo(tmp_path)
    _run(_CLAIM, repo, "area/one")

    assert _GIT is not None
    result = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [
            _GIT,
            "-C",
            str(repo),
            "rev-parse",
            "--verify",
            "--quiet",
            "refs/workspace-claimed/area/one",
        ],
        capture_output=True,
        text=True,
        check=False,  # asserting on returncode below
    )
    assert result.returncode == 0, result.stderr


def test_second_claim_gets_its_own_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ws_one = Path(_workspace(_run(_CLAIM, repo, "area/one")))

    result = _run(_CLAIM, repo, "area/two")

    assert result.returncode == 0, result.stderr
    ws_two = Path(_workspace(result))
    assert ws_two != ws_one
    assert ws_two.is_dir()
    assert ws_two == tmp_path / "repo-worktrees" / "area" / "two"


def test_invalid_branch_is_rejected_without_side_effects(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    assert _run(_CLAIM, repo, "no-slash").returncode == 2  # not <area>/<slug>
    assert _run(_CLAIM, repo, "bad/ name").returncode == 2  # invalid ref (space)

    assert _current_branch(repo) == "master"


def test_existing_branch_is_rejected(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "branch", "area/dup")

    result = _run(_CLAIM, repo, "area/dup")

    assert result.returncode == 2
    assert "already exists" in result.stderr


def test_claim_from_worktree_same_branch_is_idempotent(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ws_a = _workspace(_run(_CLAIM, repo, "area/a"))

    result = _run(_CLAIM, repo, "area/a", cwd=Path(ws_a))

    assert result.returncode == 0, result.stderr
    assert _workspace(result) == ws_a  # returns the same workspace, no new one


def test_claim_from_worktree_other_branch_creates_a_distinct_one(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ws_a = _workspace(_run(_CLAIM, repo, "area/a"))

    result = _run(_CLAIM, repo, "area/b", cwd=Path(ws_a))  # different branch

    assert result.returncode == 0, result.stderr
    ws_b = _workspace(result)
    assert ws_b != ws_a  # not silently reusing the current worktree
    assert Path(ws_b).is_dir()


def test_claim_from_within_an_unclaimed_worktree_tags_it(tmp_path: Path) -> None:
    """The idempotent same-branch path must tag, not just trust, the worktree.

    A worktree created directly with `git worktree add` (never through
    claim-workspace.sh) has no `refs/workspace-claimed/<branch>` marker.
    Running claim-workspace.sh for that branch from inside it used to report
    success without ever setting the marker — so claim said "claimed" but
    release-workspace.sh / prune-workspaces.sh would then refuse to touch it
    (PR #17 review finding). Calling claim-workspace.sh is itself an act of
    claiming: it must leave the marker set, regardless of how the worktree
    came to exist.
    """
    repo = _init_repo(tmp_path)
    manual = tmp_path / "manual-worktree"
    _git(repo, "worktree", "add", "-q", str(manual), "-b", "manual/branch")

    result = _run(_CLAIM, repo, "manual/branch", cwd=manual)

    assert result.returncode == 0, result.stderr
    assert _workspace(result) == str(manual)
    assert _GIT is not None
    marker = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [
            _GIT,
            "-C",
            str(repo),
            "rev-parse",
            "--verify",
            "--quiet",
            "refs/workspace-claimed/manual/branch",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert marker.returncode == 0, marker.stderr

    # The claim/release mismatch is now closed: release succeeds too.
    released = _run(_RELEASE, repo, "manual/branch")
    assert released.returncode == 0, released.stderr


def _marker_exists(repo: Path, branch: str) -> bool:
    assert _GIT is not None
    result = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [
            _GIT,
            "-C",
            str(repo),
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/workspace-claimed/{branch}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def test_claim_rolls_back_a_marker_it_newly_set_when_bootstrap_then_fails(
    tmp_path: Path,
) -> None:
    """A claim that never completed must not confer ownership.

    From a manually created (unmarked) worktree, if this call is the one that
    newly sets the marker and bootstrap then fails, the marker must be rolled
    back — otherwise a failed claim still leaves the worktree looking
    tool-owned to release-workspace.sh / prune-workspaces.sh (PR #17 review
    finding). The pre-existing worktree itself is untouched either way — it
    did not exist because of this call, so it is not this call's to destroy.
    """
    repo = _init_repo(tmp_path)
    manual = tmp_path / "manual-worktree"
    _git(repo, "worktree", "add", "-q", str(manual), "-b", "manual/branch")

    result = _run(_CLAIM, repo, "manual/branch", cwd=manual, bootstrap="false")

    assert result.returncode != 0
    assert not _marker_exists(repo, "manual/branch")  # rolled back
    assert manual.is_dir()  # the worktree itself survives


def test_claim_keeps_an_existing_marker_when_a_reclaim_bootstrap_fails(
    tmp_path: Path,
) -> None:
    """A transient re-bootstrap failure must not strip pre-existing ownership."""
    repo = _init_repo(tmp_path)
    ws = Path(_workspace(_run(_CLAIM, repo, "area/a")))  # a genuine successful claim

    result = _run(_CLAIM, repo, "area/a", cwd=ws, bootstrap="false")  # re-claim fails

    assert result.returncode != 0
    assert _marker_exists(repo, "area/a")  # still tagged — this call didn't set it


def test_bootstrap_failure_rolls_back_the_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    result = _run(_CLAIM, repo, "area/x", bootstrap="false")  # bootstrap fails

    assert result.returncode != 0
    assert not (tmp_path / "repo-worktrees" / "area" / "x").exists()  # worktree dir gone
    assert _GIT is not None
    branches = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(repo), "branch", "--format=%(refname:short)"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert "area/x" not in branches  # partial branch cleaned up
    worktrees = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(repo), "worktree", "list", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "area/x" not in worktrees  # no dangling worktree metadata


def test_concurrent_claims_of_distinct_branches_all_succeed(tmp_path: Path) -> None:
    """N agents claiming N distinct branches at once each get their own worktree.

    Nothing here is serialised by this script any more (no shared lock) — the
    only safety net is git's own worktree-administration locking. This is the
    scenario the always-worktree simplification is actually for.
    """
    repo = _init_repo(tmp_path)
    assert _BASH is not None
    env = os.environ.copy()
    env["WORKSPACE_BOOTSTRAP"] = "true"
    names = ["one", "two", "three", "four", "five"]

    procs = [
        subprocess.Popen(  # noqa: S603  # resolved bash, in-repo script, test env
            [_BASH, str(_CLAIM), f"area/{name}"],
            cwd=str(repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for name in names
    ]
    outs = [proc.communicate() for proc in procs]

    for proc, name in zip(procs, names, strict=True):
        assert proc.returncode == 0, f"claim for area/{name} failed"
    workspaces = [_workspace_from(stdout) for stdout, _ in outs]
    assert len(set(workspaces)) == len(names)  # every claim got a distinct worktree
    for ws in workspaces:
        assert Path(ws).is_dir()
    assert _current_branch(repo) == "master"  # main checkout was never touched


def test_release_removes_the_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ws_a = Path(_workspace(_run(_CLAIM, repo, "area/a")))

    result = _run(_RELEASE, repo, "area/a")

    assert result.returncode == 0, result.stderr
    assert not ws_a.is_dir()


def test_release_refuses_a_worktree_never_claimed_by_this_tooling(tmp_path: Path) -> None:
    """Only branches tagged by claim-workspace.sh are ever release targets.

    A worktree created directly with `git worktree add` (never through this
    tooling, so no `refs/workspace-claimed/<branch>` marker) must be refused,
    not removed — including with FORCE=1, which would otherwise discard its
    uncommitted files too (PR #17 review finding).
    """
    repo = _init_repo(tmp_path)
    manual = tmp_path / "manual-worktree"
    _git(repo, "worktree", "add", "-q", str(manual), "-b", "manual/branch")
    (manual / "uncommitted.txt").write_text("not this tooling's to discard\n")

    refused = _run(_RELEASE, repo, "manual/branch")
    assert refused.returncode != 0
    assert manual.is_dir()

    forced = _run(_RELEASE, repo, "manual/branch", force="1")
    assert forced.returncode != 0
    assert manual.is_dir()  # FORCE=1 must not override the provenance check


def test_release_refuses_master(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    result = _run(_RELEASE, repo, "master")

    assert result.returncode != 0
    assert _current_branch(repo) == "master"  # untouched


def test_release_of_unknown_branch_reports_nothing_to_release(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    result = _run(_RELEASE, repo, "area/never-claimed")

    assert result.returncode == 0, result.stderr
    assert "no workspace" in (result.stdout + result.stderr).lower()


def test_force_zero_does_not_remove_a_dirty_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ws_a = Path(_workspace(_run(_CLAIM, repo, "area/a")))
    (ws_a / "dirty.txt").write_text("uncommitted\n")  # untracked -> dirty

    refused = _run(_RELEASE, repo, "area/a", force="0")
    assert refused.returncode != 0
    assert ws_a.is_dir()  # FORCE=0 must not force

    forced = _run(_RELEASE, repo, "area/a", force="1")
    assert forced.returncode == 0, forced.stderr
    assert not ws_a.is_dir()


def test_release_removes_the_correct_worktree_under_slug_collision(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ws1 = Path(_workspace(_run(_CLAIM, repo, "a/b-c")))
    ws2 = Path(_workspace(_run(_CLAIM, repo, "a-b/c")))

    assert ws1 != ws2  # collision-free paths

    result = _run(_RELEASE, repo, "a-b/c")

    assert result.returncode == 0, result.stderr
    assert not ws2.is_dir()  # released the requested one
    assert ws1.is_dir()  # the similarly-named one survives


def test_worktree_branches_from_master_not_a_sibling_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ws_a = Path(_workspace(_run(_CLAIM, repo, "area/a")))
    (ws_a / "a.txt").write_text("work from a\n")  # commit on area/a in its own worktree
    _git(ws_a, "add", "a.txt")
    _git(ws_a, "commit", "-qm", "commit on a")

    ws_b = Path(_workspace(_run(_CLAIM, repo, "area/b")))  # a second, unrelated claim

    assert _GIT is not None
    log = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(ws_b), "log", "--oneline"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "commit on a" not in log  # b started from master, not a's HEAD
