"""Integration tests for the workspace-isolation scripts.

`claim-workspace.sh` / `release-workspace.sh` create branches and worktrees —
destructive, stateful operations — so they are exercised end to end against a
throwaway git repo, with the bootstrap step stubbed
(`WORKSPACE_BOOTSTRAP=true`) so no real `uv sync` runs. Every claim is a linked
worktree; the main checkout is never claimed (it stays on `main`). Covers the
failure and concurrency paths the scripts introduce (adversarial review of
PR #17, and the always-worktree simplification that followed it).
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
_BASH = shutil.which("bash")
_GIT = shutil.which("git")
_JUST = shutil.which("just")
_needs_just = pytest.mark.skipif(_JUST is None, reason="just CLI not installed")


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
    """A one-commit repo whose default branch is main (version-independent)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "f.txt").write_text("x\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-qm", "init")
    return repo


def _run(  # noqa: PLR0913  # test helper threading claim/release's real optional knobs individually
    script: Path,
    repo: Path,
    *args: str,
    cwd: Path | None = None,
    bootstrap: str = "true",
    force: str | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    assert _BASH is not None
    env = os.environ.copy()
    env["WORKSPACE_BOOTSTRAP"] = bootstrap
    if force is not None:
        env["FORCE"] = force
    env.update(env_extra or {})
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
    assert _current_branch(repo) == "main"  # main checkout untouched


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

    assert _current_branch(repo) == "main"


def test_claim_rejects_extra_positional_arguments(tmp_path: Path) -> None:
    """A third argument is always a typo, not a silently-ignored extra.

    Bash simply drops unreferenced positional params — without an explicit
    count check, `claim-workspace.sh area/new valid-base typo` would create
    a branch from `valid-base` as if `typo` had never been there, hiding
    whatever the caller actually meant by it (PR #23 review finding).
    """
    repo = _init_repo(tmp_path)

    result = _run(_CLAIM, repo, "area/new", "main", "typo")

    assert result.returncode == 2
    assert "usage" in result.stderr.lower()
    assert _current_branch(repo) == "main"
    assert not (tmp_path / "repo-worktrees" / "area" / "new").exists()


def test_existing_branch_is_rejected(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "branch", "area/dup")

    result = _run(_CLAIM, repo, "area/dup")

    assert result.returncode == 2
    assert "already exists" in result.stderr


def test_claim_rejects_a_branch_that_is_a_prefix_of_an_existing_one(tmp_path: Path) -> None:
    """git's ref storage forbids a branch being both a leaf and a path-prefix.

    Claiming 'area/task' when 'area/task/subtask' already exists can never
    work, with or without this tooling — but the failure should name the
    conflicting branch clearly rather than surface as git's generic
    ref-locking error (PR #17 review).
    """
    repo = _init_repo(tmp_path)
    _git(repo, "branch", "area/task/subtask")

    result = _run(_CLAIM, repo, "area/task")

    assert result.returncode == 2
    assert "area/task/subtask" in result.stderr
    assert "conflicts" in result.stderr


def test_claim_rejects_a_branch_for_which_an_existing_one_is_a_prefix(tmp_path: Path) -> None:
    """The reverse direction: 'area/task/subtask' when 'area/task' exists.

    Confirmed this cannot cause any destructive side effect even without the
    clearer pre-check message — `git worktree add -b` refuses this on its own
    and create_worktree's `created` gate (an earlier PR #17 review fix) means
    nothing gets touched — but this test also confirms the first claim's
    worktree survives fully intact.
    """
    repo = _init_repo(tmp_path)
    ws_a = Path(_workspace(_run(_CLAIM, repo, "area/task")))

    result = _run(_CLAIM, repo, "area/task/subtask")

    assert result.returncode == 2
    assert "area/task" in result.stderr
    assert "conflicts" in result.stderr
    assert ws_a.is_dir()  # the existing claim is untouched


def test_claim_from_worktree_same_branch_is_idempotent(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ws_a = _workspace(_run(_CLAIM, repo, "area/a"))

    result = _run(_CLAIM, repo, "area/a", cwd=Path(ws_a))

    assert result.returncode == 0, result.stderr
    assert _workspace(result) == ws_a  # returns the same workspace, no new one


def test_claim_rejects_an_explicit_base_on_an_idempotent_reclaim(tmp_path: Path) -> None:
    """An explicit base is meaningless once the branch already exists.

    Passing one while standing on a branch that's already checked out here
    used to be silently ignored — reporting success without ever using or
    warning about the given base, which contradicted what the caller asked
    for (PR #23 review finding). Refused outright instead.
    """
    repo = _init_repo(tmp_path)
    ws_a = _workspace(_run(_CLAIM, repo, "area/a"))

    result = _run(_CLAIM, repo, "area/a", "main", cwd=Path(ws_a))

    assert result.returncode == 2
    assert "meaningless" in result.stderr


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
    assert _current_branch(repo) == "main"  # main checkout was never touched


def test_concurrent_claims_of_the_same_branch_leave_the_winner_intact(tmp_path: Path) -> None:
    """Exactly one of two racing same-branch claims wins; the loser must never
    touch what the winner created.

    A blocker-severity PR #17 review finding: an earlier version installed an
    unconditional rollback trap before `git worktree add`. Two processes
    racing to claim the *same* branch both pass the pre-check and both reach
    `git worktree add`; git's own ref-locking lets only one actually create
    the branch, but the loser's call then fails at that exact shared
    path/branch — and an unconditional trap force-removed it and deleted the
    branch/marker regardless of which process actually owned it, destroying
    the winner's worktree out from under it. The trap now only cleans up
    resources this invocation's own `git worktree add` actually created.
    """
    repo = _init_repo(tmp_path)
    assert _BASH is not None
    env = os.environ.copy()
    env["WORKSPACE_BOOTSTRAP"] = "true"

    procs = [
        subprocess.Popen(  # noqa: S603  # resolved bash, in-repo script, test env
            [_BASH, str(_CLAIM), "area/race"],
            cwd=str(repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for _ in range(2)
    ]
    outs = [proc.communicate() for proc in procs]

    successes = [i for i, proc in enumerate(procs) if proc.returncode == 0]
    assert len(successes) == 1, (
        f"expected exactly one winner, got returncodes {[p.returncode for p in procs]}"
    )
    winner_stdout, _ = outs[successes[0]]
    ws = Path(_workspace_from(winner_stdout))

    # The winner's resources must be fully intact, not swept up by the loser.
    assert ws.is_dir()
    assert _GIT is not None
    branches = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(repo), "branch", "--format=%(refname:short)"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert "area/race" in branches
    marker = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [
            _GIT,
            "-C",
            str(repo),
            "rev-parse",
            "--verify",
            "--quiet",
            "refs/workspace-claimed/area/race",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert marker.returncode == 0


def test_release_removes_the_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ws_a = Path(_workspace(_run(_CLAIM, repo, "area/a")))

    result = _run(_RELEASE, repo, "area/a")

    assert result.returncode == 0, result.stderr
    assert not ws_a.is_dir()


def test_release_refuses_a_diverged_seeded_file_without_force(tmp_path: Path) -> None:
    """A locally-edited .env must not be silently deleted by a plain release.

    `git worktree remove` (no --force) refuses on tracked changes or
    untracked-but-not-ignored files, but .env is git-ignored — git's own
    dirty-check cannot see it at all, edited or not, so it would otherwise be
    deleted along with the rest of the worktree even without FORCE=1 (PR #17
    review, blocker; confirmed by direct reproduction before this fix).
    """
    repo = _init_repo(tmp_path)
    (repo / ".gitignore").write_text(".env\n")  # mirrors this project's real .gitignore
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-qm", "ignore .env")
    (repo / ".env").write_text("SECRET=original\n")
    ws_a = Path(_workspace(_run(_CLAIM, repo, "area/a")))
    assert (ws_a / ".env").read_text() == "SECRET=original\n"  # seeded by bootstrap
    (ws_a / ".env").write_text("SECRET=edited-by-user\n")  # a local edit worth keeping

    refused = _run(_RELEASE, repo, "area/a")
    assert refused.returncode != 0
    assert ws_a.is_dir()
    assert (ws_a / ".env").read_text() == "SECRET=edited-by-user\n"  # untouched

    forced = _run(_RELEASE, repo, "area/a", force="1")
    assert forced.returncode == 0, forced.stderr
    assert not ws_a.is_dir()


def test_release_does_not_require_force_for_an_unedited_seeded_file(tmp_path: Path) -> None:
    """The new check must not force FORCE=1 for the common, unedited case."""
    repo = _init_repo(tmp_path)
    (repo / ".gitignore").write_text(".env\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-qm", "ignore .env")
    (repo / ".env").write_text("SECRET=original\n")
    ws_a = Path(_workspace(_run(_CLAIM, repo, "area/a")))

    result = _run(_RELEASE, repo, "area/a")  # no FORCE, .env is exactly as seeded

    assert result.returncode == 0, result.stderr
    assert not ws_a.is_dir()


def test_release_refuses_an_ignored_file_never_seeded_by_bootstrap(tmp_path: Path) -> None:
    """Any ignored file is protected, not just the two bootstrap() seeds.

    A first version of this check only covered .env and
    .claude/settings.local.json specifically; .env.local (also git-ignored by
    this project's `.env.*` pattern, but never created by bootstrap() at all)
    is exactly the gap the review flagged as still open (PR #17 review,
    blocker) — nothing to compare it against in the main checkout, so its
    mere presence must block a plain release.
    """
    repo = _init_repo(tmp_path)
    (repo / ".gitignore").write_text(".env\n.env.*\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-qm", "ignore .env*")
    ws_a = Path(_workspace(_run(_CLAIM, repo, "area/a")))
    (ws_a / ".env.local").write_text("LOCAL_SECRET=1\n")  # created fresh, not seeded

    refused = _run(_RELEASE, repo, "area/a")
    assert refused.returncode != 0
    assert ws_a.is_dir()

    forced = _run(_RELEASE, repo, "area/a", force="1")
    assert forced.returncode == 0, forced.stderr
    assert not ws_a.is_dir()


def test_release_does_not_require_force_for_regenerable_ignored_artifacts(
    tmp_path: Path,
) -> None:
    """Known tooling artifacts (venvs, caches) must never demand FORCE=1.

    Every worktree accumulates these as a matter of routine `uv sync` /
    pytest / mypy / ruff use; treating them the same as a real ignored file
    would make FORCE=1 mandatory for every release, defeating the point of
    asking at all.
    """
    repo = _init_repo(tmp_path)
    (repo / ".gitignore").write_text(".venv/\n__pycache__/\n.mypy_cache/\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-qm", "ignore tooling artifacts")
    ws_a = Path(_workspace(_run(_CLAIM, repo, "area/a")))
    (ws_a / ".venv").mkdir()
    (ws_a / ".venv" / "pyvenv.cfg").write_text("home = /usr\n")
    nested_cache = ws_a / "src" / "pkg" / "__pycache__"
    nested_cache.mkdir(parents=True)
    (nested_cache / "mod.cpython-314.pyc").write_bytes(b"\x00")
    (ws_a / ".mypy_cache").mkdir()
    (ws_a / ".mypy_cache" / "CACHEDIR.TAG").write_text("Signature: x\n")

    result = _run(_RELEASE, repo, "area/a")  # no FORCE

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


def test_release_refuses_main(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    result = _run(_RELEASE, repo, "main")

    assert result.returncode != 0
    assert _current_branch(repo) == "main"  # untouched


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


def test_worktree_branches_from_main_not_a_sibling_worktree(tmp_path: Path) -> None:
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
    assert "commit on a" not in log  # b started from main, not a's HEAD


def test_claim_with_an_explicit_base_stacks_on_it(tmp_path: Path) -> None:
    """The opt-in counterpart to the test above: given a base, do inherit it.

    Splitting a task into dependent PRs (claim `models/part-2` from
    `models/part-1` before the latter has merged) needs exactly the commits
    the default-base test above proves a claim normally does *not* pick up.
    """
    repo = _init_repo(tmp_path)
    ws_a = Path(_workspace(_run(_CLAIM, repo, "area/a")))
    (ws_a / "a.txt").write_text("work from a\n")
    _git(ws_a, "add", "a.txt")
    _git(ws_a, "commit", "-qm", "commit on a")

    result = _run(_CLAIM, repo, "area/b", "area/a")  # explicit base: area/a

    assert result.returncode == 0, result.stderr
    ws_b = Path(_workspace(result))
    assert _GIT is not None
    log = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(ws_b), "log", "--oneline"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "commit on a" in log  # b explicitly stacked on a, so it inherits it


def test_claim_with_an_explicit_base_of_a_tag_or_sha(tmp_path: Path) -> None:
    """The base override accepts any commit-ish, not just a branch name — and
    actually uses it, rather than silently falling back to main's tip.

    A first version of this test tagged/SHA-referenced main's own tip, so
    an implementation that accepted the argument but ignored it would have
    passed too (PR #23 review finding). Points the tag and the SHA at a
    commit unreachable from main instead, so only a claim that genuinely
    used that base ends up with its content.
    """
    repo = _init_repo(tmp_path)
    assert _GIT is not None
    _git(repo, "checkout", "-qb", "scratch")
    (repo / "scratch.txt").write_text("not reachable from main\n")
    _git(repo, "add", "scratch.txt")
    _git(repo, "commit", "-qm", "scratch commit")
    sha = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _git(repo, "tag", "v0")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "branch", "-D", "scratch")  # only the tag/SHA keep it reachable

    by_tag = _run(_CLAIM, repo, "area/from-tag", "v0")
    assert by_tag.returncode == 0, by_tag.stderr
    assert (Path(_workspace(by_tag)) / "scratch.txt").exists()

    by_sha = _run(_CLAIM, repo, "area/from-sha", sha)
    assert by_sha.returncode == 0, by_sha.stderr
    assert (Path(_workspace(by_sha)) / "scratch.txt").exists()


def test_claim_with_an_explicit_base_starting_with_a_hyphen(tmp_path: Path) -> None:
    """A ref name starting with "-" is valid per `check-ref-format` (verified
    directly), even though `git branch`/`git tag` refuse to create one —
    `update-ref` doesn't share that extra guard, so such a ref can genuinely
    exist. Without treating it as "end of options", git parses it as a flag
    instead of a revision and wrongly reports a real ref as not resolving
    (PR #23 review finding).
    """
    repo = _init_repo(tmp_path)
    assert _GIT is not None
    sha = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _git(repo, "update-ref", "refs/heads/-hyphenated", sha)

    result = _run(_CLAIM, repo, "area/from-hyphen", "-hyphenated")

    assert result.returncode == 0, result.stderr


def test_claim_rejects_an_ambiguous_explicit_base(tmp_path: Path) -> None:
    """A base matching both a branch and a tag must be refused, not silently
    resolved to whichever one git's own precedence happens to prefer.

    Plain `git rev-parse` succeeds for an ambiguous short name (it just picks
    one, per its own documented precedence — tags before branches). Detected
    structurally here — by checking each ref namespace directly, not by
    parsing git's own (suppressible, locale-dependent) diagnostic text — see
    `test_claim_rejects_an_ambiguous_base_even_with_git_warnings_disabled`
    for why that mattered (PR #23 review finding).
    """
    repo = _init_repo(tmp_path)
    ws_a = Path(_workspace(_run(_CLAIM, repo, "area/a")))
    (ws_a / "a.txt").write_text("work from a\n")
    _git(ws_a, "add", "a.txt")
    _git(ws_a, "commit", "-qm", "commit on a")  # branch "collide" candidate
    _git(repo, "branch", "collide", "area/a")
    _git(repo, "tag", "collide")  # tag "collide" at main's tip — a different commit

    result = _run(_CLAIM, repo, "area/new", "collide")

    assert result.returncode == 2
    assert "ambiguous" in result.stderr
    assert _GIT is not None
    branches = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(repo), "branch", "--format=%(refname:short)"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert "area/new" not in branches


def test_claim_rejects_an_ambiguous_base_even_with_git_warnings_disabled(
    tmp_path: Path,
) -> None:
    """Ambiguity detection must not depend on git choosing to warn at all.

    An earlier version matched git's own "refname ... is ambiguous" text on
    stderr. Two separate PR #23 review findings broke that assumption: the
    warning is locale-dependent (a translated message would not contain that
    English substring — verified by temporarily reverting an LC_ALL=C fix
    for exactly this and confirming ambiguity detection silently failed), and
    it is outright suppressible via `core.warnAmbiguousRefs=false` — verified
    directly: with that config set, `git rev-parse` on a colliding name
    still succeeds and still silently picks a ref, but prints nothing at all,
    no matter the locale. Detection is now structural (checks each ref
    namespace directly, never git's diagnostic output), so it cannot be
    defeated by suppressing or translating a message that no longer matters.
    """
    repo = _init_repo(tmp_path)
    _git(repo, "config", "core.warnAmbiguousRefs", "false")
    ws_a = Path(_workspace(_run(_CLAIM, repo, "area/a")))
    (ws_a / "a.txt").write_text("work from a\n")
    _git(ws_a, "add", "a.txt")
    _git(ws_a, "commit", "-qm", "commit on a")
    _git(repo, "branch", "collide", "area/a")
    _git(repo, "tag", "collide")

    result = _run(_CLAIM, repo, "area/new", "collide")

    assert result.returncode == 2
    assert "ambiguous" in result.stderr


def test_claim_rejects_an_ambiguous_base_from_a_pseudoref_collision(tmp_path: Path) -> None:
    """A branch/tag can collide with a pseudoref (HEAD, ORIG_HEAD, ...), not
    just with each other.

    `git reset --hard` creates a real `ORIG_HEAD` pseudoref (a plain file at
    the top of .git/, not under refs/ at all — a separate git ref tier from
    branches/tags/remotes); a branch or tag can then also be named
    `ORIG_HEAD`, pointing anywhere. gitrevisions(7) puts pseudorefs at the
    *highest* precedence tier, so `git rev-parse ORIG_HEAD` would silently
    prefer the pseudoref over the branch with zero indication (PR #23 review
    finding — the first structural-detection version only checked
    refs/, refs/tags/, refs/heads/, refs/remotes/, missing this tier
    entirely).
    """
    repo = _init_repo(tmp_path)
    _git(repo, "commit", "--allow-empty", "-qm", "second")
    _git(repo, "reset", "--hard", "HEAD~1")  # creates .git/ORIG_HEAD for real
    ws_a = Path(_workspace(_run(_CLAIM, repo, "area/a")))
    (ws_a / "a.txt").write_text("work from a\n")
    _git(ws_a, "add", "a.txt")
    _git(ws_a, "commit", "-qm", "commit on a")
    _git(repo, "branch", "ORIG_HEAD", "area/a")  # collides with the real pseudoref

    result = _run(_CLAIM, repo, "area/new", "ORIG_HEAD")

    assert result.returncode == 2
    assert "ambiguous" in result.stderr


def test_claim_rejects_an_ambiguous_base_from_any_pseudoref_generically(
    tmp_path: Path,
) -> None:
    """Pseudoref detection is generic — any file under .git/, not a hardcoded
    name list.

    A first version only recognized a fixed set of well-known pseudoref
    names and missed REBASE_HEAD (created during a conflicted rebase, not in
    that list) — less correct than just asking the filesystem whether
    $GIT_DIR/<name> exists at all (PR #23 review finding). Synthesises
    REBASE_HEAD directly rather than orchestrating a real conflicting
    rebase, since the mechanism under test no longer cares what the name is.
    """
    repo = _init_repo(tmp_path)
    ws_a = Path(_workspace(_run(_CLAIM, repo, "area/a")))
    (ws_a / "a.txt").write_text("work from a\n")
    _git(ws_a, "add", "a.txt")
    _git(ws_a, "commit", "-qm", "commit on a")
    assert _GIT is not None
    main_sha = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(repo), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (repo / ".git" / "REBASE_HEAD").write_text(main_sha + "\n")
    _git(repo, "branch", "REBASE_HEAD", "area/a")  # collides with the synthesised pseudoref

    result = _run(_CLAIM, repo, "area/new", "REBASE_HEAD")

    assert result.returncode == 2
    assert "ambiguous" in result.stderr


def test_claim_rejects_an_ambiguous_base_from_a_remote_head_collision(tmp_path: Path) -> None:
    """A branch can collide with a remote's symbolic HEAD of the same name.

    `refs/remotes/<name>/HEAD` is its own tier in gitrevisions(7)'s
    precedence order, distinct from `refs/heads/<name>` and
    `refs/remotes/<name>` (a branch actually named `<name>` under that
    remote) — synthesised directly via `update-ref`, the same way this
    project's own `refs/workspace-claimed/*` marker is (PR #23 review
    finding: the first structural-detection version omitted this tier too).
    """
    repo = _init_repo(tmp_path)
    ws_a = Path(_workspace(_run(_CLAIM, repo, "area/a")))
    (ws_a / "a.txt").write_text("work from a\n")
    _git(ws_a, "add", "a.txt")
    _git(ws_a, "commit", "-qm", "commit on a")
    _git(repo, "update-ref", "refs/remotes/collide/HEAD", "main")
    _git(repo, "branch", "collide", "area/a")

    result = _run(_CLAIM, repo, "area/new", "collide")

    assert result.returncode == 2
    assert "ambiguous" in result.stderr


def test_claim_with_explicit_head_base_resolves_in_the_callers_worktree(
    tmp_path: Path,
) -> None:
    """`HEAD` as an explicit base must resolve in the caller's own context.

    Every git call after validation runs `-C "$main_root"` (the main
    checkout, always on main), so a context-sensitive revision like `HEAD`
    would otherwise mean something different there than what the caller —
    standing inside a different worktree entirely — actually intended:
    claiming with base `HEAD` from inside a sibling worktree would silently
    branch from main's HEAD instead of that worktree's real one (PR #23
    review finding). The base is resolved to an absolute commit OID up front,
    in the caller's actual cwd, specifically to close this.
    """
    repo = _init_repo(tmp_path)
    ws_a = Path(_workspace(_run(_CLAIM, repo, "area/a")))
    (ws_a / "a.txt").write_text("work from a\n")
    _git(ws_a, "add", "a.txt")
    _git(ws_a, "commit", "-qm", "commit on a")

    # Claim area/b with base "HEAD", invoked FROM inside area/a's worktree —
    # HEAD there is area/a's tip, not main's.
    result = _run(_CLAIM, repo, "area/b", "HEAD", cwd=ws_a)

    assert result.returncode == 0, result.stderr
    ws_b = Path(_workspace(result))
    assert (ws_b / "a.txt").exists()  # inherited area/a's tip, not main's


def test_claim_rejects_an_invalid_explicit_base(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    result = _run(_CLAIM, repo, "area/b", "no-such-branch")

    assert result.returncode == 2
    assert "no-such-branch" in result.stderr
    assert _GIT is not None
    branches = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(repo), "branch", "--format=%(refname:short)"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert "area/b" not in branches  # rejected before anything was created


def test_claim_rejects_an_explicit_empty_base(tmp_path: Path) -> None:
    """An explicitly-empty base ("") must be rejected, not treated as omitted.

    `${2:-}` cannot distinguish a genuinely omitted argument from one
    present-but-empty — and `just claim-workspace <branch>` (the ordinary
    no-base invocation) resolves its own unset `base=""` just default, so
    the *common* path forwards an explicit empty string unless the recipe
    itself omits $2 entirely (fixed alongside this). Argument count
    (`base_given`, from `$#`), not the value of $2, is what the script now
    keys on (PR #23 review finding).
    """
    repo = _init_repo(tmp_path)

    result = _run(_CLAIM, repo, "area/b", "")

    assert result.returncode == 2
    assert "empty" in result.stderr.lower()
    assert _GIT is not None
    branches = subprocess.run(  # noqa: S603  # resolved git path, test repo
        [_GIT, "-C", str(repo), "branch", "--format=%(refname:short)"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert "area/b" not in branches


@_needs_just
def test_just_claim_workspace_recipe_forwards_argument_count_faithfully(
    tmp_path: Path,
) -> None:
    """The public `just claim-workspace` entry point, not just the script.

    A first version of the recipe used a defaulted parameter (`base=""`),
    which `just` always resolves to *some* value before the recipe body runs
    — indistinguishable from an explicit empty string, so `just
    claim-workspace <branch> ""` reached the script the same as omitting the
    argument entirely (PR #23 review finding). Switched to a variadic
    parameter (`*base`); this drives the *actual* justfile against a stub
    claim-workspace.sh that records exactly what it received, proving `just`
    itself forwards argument count faithfully — not just that the script
    would handle it correctly if it got the arguments right.

    `just` always changes into the directory containing the justfile before
    running a recipe (verified directly), so the real justfile is copied
    into a throwaway directory rather than run in place — running it against
    this repo's own scripts/claim-workspace.sh would claim a real workspace.
    """
    assert _JUST is not None
    real_repo_root = Path(__file__).parents[2]
    workdir = tmp_path / "justdir"
    workdir.mkdir()
    shutil.copy(real_repo_root / "justfile", workdir / "justfile")
    (workdir / "scripts").mkdir()
    args_file = workdir / "args.txt"
    stub = workdir / "scripts" / "claim-workspace.sh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "{\n"
        "    printf '%s\\n' \"$#\"\n"
        '    for a in "$@"; do printf \'[%s]\\n\' "$a"; done\n'
        f'}} >"{args_file}"\n'
    )
    stub.chmod(0o755)

    def _just(*args: str) -> None:
        assert _JUST is not None
        subprocess.run(  # noqa: S603  # resolved just path, test-controlled dir
            [_JUST, *args], cwd=str(workdir), check=True, capture_output=True, text=True
        )

    _just("claim-workspace", "area/omit")
    assert args_file.read_text().splitlines() == ["1", "[area/omit]"]

    _just("claim-workspace", "area/empty", "")
    assert args_file.read_text().splitlines() == ["2", "[area/empty]", "[]"]

    _just("claim-workspace", "area/base", "main")
    assert args_file.read_text().splitlines() == ["2", "[area/base]", "[main]"]
