"""Integration tests for the workspace *fleet* helpers.

`list-workspaces.sh` (observability), `prune-workspaces.sh` (cleanup of
merged/closed branches' worktrees), and `claim-workspaces.sh` (batch parallel
claim) exist because claim-workspace.sh's always-worktree model (see
test_workspace.py) makes running several agents in parallel the normal case,
not an edge case — these are the tools for tracking and tearing down that
fleet. Exercised end to end against a throwaway git repo, same as
test_workspace.py.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).parents[2] / "scripts"
_CLAIM = _SCRIPTS / "claim-workspace.sh"
_LIST = _SCRIPTS / "list-workspaces.sh"
_PRUNE = _SCRIPTS / "prune-workspaces.sh"
_CLAIM_MANY = _SCRIPTS / "claim-workspaces.sh"
_BASH = shutil.which("bash")
_GIT = shutil.which("git")
_GH = shutil.which("gh")


def _git(repo: Path, *args: str) -> None:
    assert _GIT is not None
    subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [_GIT, "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


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
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    assert _BASH is not None
    env = os.environ.copy()
    env.update(env_extra or {})
    return subprocess.run(  # noqa: S603  # resolved bash, in-repo script, test env
        [_BASH, str(script), *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=env,
        check=False,  # tests assert on returncode, including the failure paths
    )


def _claim(repo: Path, branch: str) -> str:
    result = _run(_CLAIM, repo, branch, env_extra={"WORKSPACE_BOOTSTRAP": "true"})
    assert result.returncode == 0, result.stderr
    for line in result.stdout.splitlines():
        if line.startswith("WORKSPACE="):
            return line.removeprefix("WORKSPACE=")
    msg = f"no WORKSPACE= line in output:\n{result.stdout}"
    raise AssertionError(msg)


# --- list-workspaces.sh ------------------------------------------------------


def test_list_shows_main_and_every_claimed_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _claim(repo, "area/one")
    _claim(repo, "area/two")

    result = _run(_LIST, repo)

    assert result.returncode == 0, result.stderr
    assert "master (main, integration-only)" in result.stdout
    assert "area/one" in result.stdout
    assert "area/two" in result.stdout


def test_list_marks_a_dirty_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ws = Path(_claim(repo, "area/a"))
    (ws / "dirty.txt").write_text("uncommitted\n")

    result = _run(_LIST, repo)

    lines = {line.split()[0]: line for line in result.stdout.splitlines() if "area/a" in line}
    assert "dirty" in lines["area/a"]


# --- claim-workspaces.sh -----------------------------------------------------


def test_claim_many_claims_every_branch_concurrently(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    result = _run(
        _CLAIM_MANY,
        repo,
        "area/one",
        "area/two",
        "area/three",
        env_extra={"WORKSPACE_BOOTSTRAP": "true"},
    )

    assert result.returncode == 0, result.stderr
    workspaces = [
        line.removeprefix("WORKSPACE=")
        for line in result.stdout.splitlines()
        if line.startswith("WORKSPACE=")
    ]
    assert len(workspaces) == 3
    assert len(set(workspaces)) == 3  # all distinct
    for ws in workspaces:
        assert Path(ws).is_dir()


def test_claim_many_reports_a_failure_without_dropping_the_others(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    result = _run(
        _CLAIM_MANY,
        repo,
        "area/good",
        "not-a-valid-branch",  # missing <area>/<slug> slash -> claim-workspace.sh rejects it
        env_extra={"WORKSPACE_BOOTSTRAP": "true"},
    )

    assert result.returncode == 1
    assert "WORKSPACE=" in result.stdout  # the good claim still succeeded
    assert "not-a-valid-branch" in result.stderr
    assert (tmp_path / "repo-worktrees" / "area" / "good").is_dir()


# --- prune-workspaces.sh ------------------------------------------------------

_needs_gh = pytest.mark.skipif(_GH is None, reason="gh CLI not installed")


@_needs_gh
def test_prune_reports_no_pr_for_a_branch_with_no_remote(tmp_path: Path) -> None:
    # The throwaway repo has no GitHub remote at all, so `gh pr list` fails fast
    # locally (no network round trip) and the branch is correctly never treated
    # as a prune candidate.
    repo = _init_repo(tmp_path)
    _claim(repo, "area/a")

    result = _run(_PRUNE, repo)

    assert result.returncode == 0, result.stderr
    assert "no-pr" in result.stdout
    assert (tmp_path / "repo-worktrees" / "area" / "a").is_dir()  # nothing removed


@_needs_gh
def test_prune_skips_a_dirty_worktree_even_with_force(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ws = Path(_claim(repo, "area/a"))
    (ws / "dirty.txt").write_text("uncommitted\n")

    result = _run(_PRUNE, repo, env_extra={"FORCE": "1"})

    assert result.returncode == 0, result.stderr
    assert "dirty-skip" in result.stdout
    assert ws.is_dir()  # never touched, forced or not


def test_prune_without_gh_fails_loudly(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _claim(repo, "area/a")
    assert _GIT is not None
    # A PATH pointing at git's own directory would usually hide `gh`, but not
    # reliably — some environments (e.g. the CI runner) install both in the
    # same bin directory. A synthetic directory containing only a `git` shim
    # hides `gh` regardless of how the real filesystem is laid out.
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    git_shim = stub_bin / "git"
    git_shim.write_text(f"#!/usr/bin/env bash\nexec '{_GIT}' \"$@\"\n")
    git_shim.chmod(0o755)

    result = _run(_PRUNE, repo, env_extra={"PATH": str(stub_bin)})

    assert result.returncode == 1
    assert "gh cli not found" in result.stderr.lower()
