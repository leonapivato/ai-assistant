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
_RELEASE = _SCRIPTS / "release-workspace.sh"
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


def _stub_gh(tmp_path: Path) -> Path:
    """A directory with a fake `gh` that fabricates `pr list` responses.

    Prepend this to PATH (never replace it) so real git/awk/sed etc. keep
    resolving normally through the rest of PATH — only `gh` itself is swapped
    out. Behaviour is driven by FAKE_GH_STATE / FAKE_GH_HEAD_SHA / FAKE_GH_EXIT
    env vars read at invocation time, so one script serves every
    scenario below without needing real `gh` auth or a GitHub remote.
    """
    stub_bin = tmp_path / "fake-gh-bin"
    stub_bin.mkdir()
    gh_stub = stub_bin / "gh"
    gh_stub.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1 $2" == "pr list" ]]; then\n'
        '    if [[ "${FAKE_GH_EXIT:-0}" != "0" ]]; then\n'
        '        echo "simulated gh failure" >&2\n'
        "        exit 1\n"
        "    fi\n"
        '    printf \'%s\\t%s\\n\' "${FAKE_GH_STATE:-}" "${FAKE_GH_HEAD_SHA:-}"\n'
        "    exit 0\n"
        "fi\n"
        'echo "unsupported fake gh invocation: $*" >&2\n'
        "exit 1\n"
    )
    gh_stub.chmod(0o755)
    return stub_bin


def _run_with_fake_gh(
    repo: Path,
    *,
    state: str = "",
    head_sha: str = "",
    fail: bool = False,
    force: bool = False,
) -> subprocess.CompletedProcess[str]:
    stub_bin = _stub_gh(repo.parent)
    env_extra = {
        "PATH": f"{stub_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        "FAKE_GH_STATE": state,
        "FAKE_GH_HEAD_SHA": head_sha,
        "FAKE_GH_EXIT": "1" if fail else "0",
    }
    if force:
        env_extra["FORCE"] = "1"
    return _run(_PRUNE, repo, env_extra=env_extra)


def _head_sha(path: Path) -> str:
    assert _GIT is not None
    out = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def test_prune_reports_no_pr_when_gh_finds_no_matching_pr(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ws = Path(_claim(repo, "area/a"))

    result = _run_with_fake_gh(repo, state="")  # gh succeeds; empty result

    assert result.returncode == 0, result.stderr
    assert "no-pr" in result.stdout
    assert ws.is_dir()  # nothing removed


def test_prune_removes_a_merged_branch_whose_head_matches_the_pr(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ws = Path(_claim(repo, "area/a"))
    sha = _head_sha(ws)

    result = _run_with_fake_gh(repo, state="MERGED", head_sha=sha, force=True)

    assert result.returncode == 0, result.stderr
    assert "PRUNE(merged)" in result.stdout
    assert not ws.is_dir()


def test_prune_dry_run_reports_merged_without_removing(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ws = Path(_claim(repo, "area/a"))
    sha = _head_sha(ws)

    result = _run_with_fake_gh(repo, state="MERGED", head_sha=sha)  # no FORCE

    assert result.returncode == 0, result.stderr
    assert "PRUNE(merged)" in result.stdout
    assert ws.is_dir()  # dry run never removes


def test_prune_keeps_a_reused_branch_name_whose_head_has_moved_on(tmp_path: Path) -> None:
    """A new claim can legitimately reuse an old, already-pruned branch name.

    Its worktree's HEAD will not match the old PR's recorded head commit, so
    it must never be treated as a prune candidate from the name match alone —
    that would force-delete unrelated, possibly unpushed, new work (PR #17
    review finding).
    """
    repo = _init_repo(tmp_path)
    ws = Path(_claim(repo, "area/a"))
    (ws / "new-work.txt").write_text("unrelated new work\n")
    _git(ws, "add", "new-work.txt")
    _git(ws, "commit", "-qm", "new work on a reused branch name")

    stale_sha = "0" * 40  # the old, merged PR's head — not this worktree's

    result = _run_with_fake_gh(repo, state="MERGED", head_sha=stale_sha, force=True)

    assert result.returncode == 0, result.stderr
    assert "head-changed" in result.stdout
    assert ws.is_dir()  # never removed


def test_prune_treats_closed_the_same_as_merged(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ws = Path(_claim(repo, "area/a"))
    sha = _head_sha(ws)

    result = _run_with_fake_gh(repo, state="CLOSED", head_sha=sha, force=True)

    assert result.returncode == 0, result.stderr
    assert "PRUNE(closed)" in result.stdout
    assert not ws.is_dir()


def test_prune_frees_a_released_branch_whose_head_matches_the_pr(tmp_path: Path) -> None:
    """The documented "release after merge, then prune" flow must actually work.

    release-workspace.sh removes the worktree but keeps the branch, by design
    (see its header) — so prune-workspaces.sh must find that branch by
    scanning refs, not just live worktrees, or a released branch could never
    be pruned and its name never reused (PR #17 review finding: pruning only
    iterated `git worktree list`, so a released branch was invisible to it).
    """
    repo = _init_repo(tmp_path)
    ws = Path(_claim(repo, "area/a"))
    sha = _head_sha(ws)

    released = _run(_RELEASE, repo, "area/a")
    assert released.returncode == 0, released.stderr
    assert not ws.is_dir()

    result = _run_with_fake_gh(repo, state="MERGED", head_sha=sha, force=True)

    assert result.returncode == 0, result.stderr
    assert "PRUNE(merged)" in result.stdout
    assert _GIT is not None
    branches = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(repo), "branch", "--format=%(refname:short)"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert "area/a" not in branches  # branch actually freed

    reclaimed = _run(_CLAIM, repo, "area/a", env_extra={"WORKSPACE_BOOTSTRAP": "true"})
    assert reclaimed.returncode == 0, reclaimed.stderr  # the name is genuinely reusable now


def test_prune_keeps_an_open_pr_even_with_force(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ws = Path(_claim(repo, "area/a"))

    result = _run_with_fake_gh(repo, state="OPEN", force=True)

    assert result.returncode == 0, result.stderr
    assert "keep" in result.stdout
    assert ws.is_dir()


def test_prune_reports_lookup_error_and_exits_nonzero(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ws = Path(_claim(repo, "area/a"))

    result = _run_with_fake_gh(repo, fail=True, force=True)

    assert result.returncode == 1  # had_error propagates past the loop's subshell
    assert "lookup-error" in result.stdout
    assert ws.is_dir()  # never a prune candidate


@_needs_gh
def test_prune_reports_lookup_error_when_gh_cannot_resolve_a_remote(tmp_path: Path) -> None:
    # The throwaway repo has no GitHub remote at all, so the real `gh pr list`
    # genuinely fails (not "succeeds with an empty result") — that must surface
    # as lookup-error, not be folded into no-pr.
    repo = _init_repo(tmp_path)
    _claim(repo, "area/a")

    result = _run(_PRUNE, repo)

    assert result.returncode == 1
    assert "lookup-error" in result.stdout
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
