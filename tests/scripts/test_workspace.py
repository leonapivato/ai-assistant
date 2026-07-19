"""Integration tests for the workspace-isolation scripts.

`claim-workspace.sh` / `release-workspace.sh` create branches, worktrees, and a
lock — destructive, stateful operations — so they are exercised end to end
against a throwaway git repo, with the bootstrap step stubbed
(`WORKSPACE_BOOTSTRAP=true`) so no real `uv sync` runs. Covers the failure and
concurrency paths the scripts introduce (adversarial review of PR #17).
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


def _lock(repo: Path) -> Path:
    return repo / ".git" / "main-workspace.lock"


def test_first_claim_uses_main_checkout(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    result = _run(_CLAIM, repo, "area/one")

    assert result.returncode == 0, result.stderr
    assert _workspace(result) == str(repo)
    assert _current_branch(repo) == "area/one"
    assert _lock(repo).exists()


def test_second_claim_gets_a_worktree_when_main_is_locked(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(_CLAIM, repo, "area/one")  # claims main

    result = _run(_CLAIM, repo, "area/two")  # main locked -> worktree

    assert result.returncode == 0, result.stderr
    ws = Path(_workspace(result))
    assert ws != repo
    assert ws.is_dir()
    assert ws == tmp_path / "repo-worktrees" / "area" / "two"


def test_invalid_branch_is_rejected_without_side_effects(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    assert _run(_CLAIM, repo, "no-slash").returncode == 2  # not <area>/<slug>
    assert _run(_CLAIM, repo, "bad/ name").returncode == 2  # invalid ref (space)

    assert not _lock(repo).exists()
    assert _current_branch(repo) == "master"


def test_existing_branch_is_rejected(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "branch", "area/dup")

    result = _run(_CLAIM, repo, "area/dup")

    assert result.returncode == 2
    assert "already exists" in result.stderr


def test_claim_from_worktree_same_branch_is_idempotent(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(_CLAIM, repo, "area/a")  # main
    ws_b = _workspace(_run(_CLAIM, repo, "area/b"))  # worktree

    result = _run(_CLAIM, repo, "area/b", cwd=Path(ws_b))

    assert result.returncode == 0, result.stderr
    assert _workspace(result) == ws_b  # returns the same workspace, no new one


def test_claim_from_worktree_other_branch_creates_a_distinct_one(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(_CLAIM, repo, "area/a")  # main
    ws_b = _workspace(_run(_CLAIM, repo, "area/b"))  # worktree

    result = _run(_CLAIM, repo, "area/c", cwd=Path(ws_b))  # different branch

    assert result.returncode == 0, result.stderr
    ws_c = _workspace(result)
    assert ws_c != ws_b  # not silently reusing the current worktree
    assert Path(ws_c).is_dir()


def test_bootstrap_failure_rolls_back_the_main_claim(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    result = _run(_CLAIM, repo, "area/x", bootstrap="false")  # bootstrap fails

    assert result.returncode != 0
    assert not _lock(repo).exists()  # lock released
    assert _current_branch(repo) == "master"  # main restored
    assert _GIT is not None
    branches = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(repo), "branch", "--format=%(refname:short)"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert "area/x" not in branches  # partial branch cleaned up


def test_bootstrap_failure_rolls_back_a_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(_CLAIM, repo, "area/a")  # claims main, so the next claim uses a worktree

    result = _run(_CLAIM, repo, "area/b", bootstrap="false")  # worktree bootstrap fails

    assert result.returncode != 0
    assert not (tmp_path / "repo-worktrees" / "area" / "b").exists()  # worktree dir gone
    assert _GIT is not None
    branches = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(repo), "branch", "--format=%(refname:short)"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert "area/b" not in branches  # partial branch cleaned up
    worktrees = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(repo), "worktree", "list", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "area/b" not in worktrees  # no dangling worktree metadata


def test_concurrent_claims_give_main_to_exactly_one(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    assert _BASH is not None
    env = os.environ.copy()
    env["WORKSPACE_BOOTSTRAP"] = "true"

    procs = [
        subprocess.Popen(  # noqa: S603  # resolved bash, in-repo script, test env
            [_BASH, str(_CLAIM), f"area/{name}"],
            cwd=str(repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for name in ("one", "two")
    ]
    outs = [proc.communicate() for proc in procs]

    for proc in procs:
        assert proc.returncode == 0
    workspaces = [_workspace_from(stdout) for stdout, _ in outs]
    # The atomic lock guarantees exactly one claim lands in the main checkout.
    assert sum(w == str(repo) for w in workspaces) == 1


def test_release_clears_a_recorded_stale_lock(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _lock(repo).write_text("area/ghost\n")  # lock left by a dead claim (main on master)

    result = _run(_RELEASE, repo, "area/ghost")  # release by the recorded branch

    assert result.returncode == 0, result.stderr
    assert not _lock(repo).exists()


def test_release_of_a_non_owning_branch_leaves_the_lock_intact(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(_CLAIM, repo, "area/a")  # claims main; the lock records area/a

    result = _run(_RELEASE, repo, "area/other")  # a branch that owns no workspace

    # Must NOT reap a lock it does not own — that was the concurrent-claim
    # corruption path. The real owner is reported instead.
    assert _lock(repo).exists()
    assert "area/a" in result.stdout + result.stderr


def test_claim_fails_loudly_if_revoked_during_bootstrap(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    assert _GIT is not None
    # Bootstrap that simulates a concurrent release: drop the lock and move HEAD
    # back to master while the claim is still "bootstrapping".
    sabotage = tmp_path / "sabotage.sh"
    sabotage.write_text(
        f"#!/usr/bin/env bash\nrm -f '{_lock(repo)}'\n{_GIT} -C '{repo}' checkout -q master\n"
    )
    sabotage.chmod(0o755)

    result = _run(_CLAIM, repo, "area/a", bootstrap=str(sabotage))

    assert result.returncode != 0
    assert "WORKSPACE=" not in result.stdout  # no phantom success reported
    assert "revoked" in result.stderr.lower()


def test_forced_main_release_removes_untracked_nested_repo(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(_CLAIM, repo, "area/a")
    nested = repo / "vendored"
    nested.mkdir()
    _git(nested, "init", "-q")  # an untracked *nested* git repo (needs clean -ff)

    result = _run(_RELEASE, repo, "area/a", force="1")

    assert result.returncode == 0, result.stderr
    assert not nested.exists()  # -ff removed the nested repo
    assert not _lock(repo).exists()
    assert _GIT is not None
    status = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(repo), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert status == ""


def test_force_zero_does_not_remove_a_dirty_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(_CLAIM, repo, "area/a")  # main
    ws_b = Path(_workspace(_run(_CLAIM, repo, "area/b")))  # worktree
    (ws_b / "dirty.txt").write_text("uncommitted\n")  # untracked -> dirty

    refused = _run(_RELEASE, repo, "area/b", force="0")
    assert refused.returncode != 0
    assert ws_b.is_dir()  # FORCE=0 must not force

    forced = _run(_RELEASE, repo, "area/b", force="1")
    assert forced.returncode == 0, forced.stderr
    assert not ws_b.is_dir()


def test_release_removes_the_correct_worktree_under_slug_collision(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(_CLAIM, repo, "area/a")  # main
    ws1 = Path(_workspace(_run(_CLAIM, repo, "a/b-c")))  # worktree
    ws2 = Path(_workspace(_run(_CLAIM, repo, "a-b/c")))  # distinct worktree

    assert ws1 != ws2  # collision-free paths

    result = _run(_RELEASE, repo, "a-b/c")

    assert result.returncode == 0, result.stderr
    assert not ws2.is_dir()  # released the requested one
    assert ws1.is_dir()  # the similarly-named one survives


def test_worktree_branches_from_master_not_main_head(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(_CLAIM, repo, "area/a")  # claims main; main HEAD is now area/a
    (repo / "a.txt").write_text("work from a\n")  # commit on area/a in the main checkout
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-qm", "commit on a")

    ws_b = Path(_workspace(_run(_CLAIM, repo, "area/b")))  # worktree for a second PR

    assert _GIT is not None
    log = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(ws_b), "log", "--oneline"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "commit on a" not in log  # b started from master, not a's HEAD


def test_clean_main_release_returns_to_master(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(_CLAIM, repo, "area/a")

    result = _run(_RELEASE, repo, "area/a")

    assert result.returncode == 0, result.stderr
    assert _current_branch(repo) == "master"
    assert not _lock(repo).exists()


def test_unforced_main_release_refuses_when_dirty(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(_CLAIM, repo, "area/a")
    (repo / "junk.txt").write_text("untracked\n")

    result = _run(_RELEASE, repo, "area/a")  # no FORCE

    assert result.returncode != 0
    assert _lock(repo).exists()  # not released
    assert _current_branch(repo) == "area/a"  # left as-is


def test_forced_main_release_discards_tracked_and_untracked(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(_CLAIM, repo, "area/a")
    (repo / "f.txt").write_text("modified\n")  # tracked change
    (repo / "junk.txt").write_text("untracked\n")  # untracked file

    result = _run(_RELEASE, repo, "area/a", force="1")

    assert result.returncode == 0, result.stderr
    assert _current_branch(repo) == "master"
    assert not _lock(repo).exists()
    assert not (repo / "junk.txt").exists()  # untracked discarded too
    assert _GIT is not None
    status = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(repo), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert status == ""  # main is genuinely clean, so future claims can use it
