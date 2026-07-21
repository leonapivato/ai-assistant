"""Tests for the default base-ref resolution in scripts/codex-review.sh.

An earlier version defaulted to the literal string "main" — the local
branch ref, which nothing in this workflow keeps current (worktrees branch
from origin/main directly; see claim-workspace.sh) and can sit stale
indefinitely. Reviewing against it can silently diff a completely different,
larger range than CI's merge-relative one. Fixed to prefer origin/main when
known, matching claim-workspace.sh's own resolution. Driven as a subprocess
with a fake ``codex`` on ``PATH`` so no OpenAI call happens; the resolved
base is read off the script's own "review of HEAD vs '<base>'" stderr line.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _fake_codex import run_review

_GIT = shutil.which("git")


def _git(repo: Path, *args: str) -> None:
    assert _GIT is not None
    subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [_GIT, *args], cwd=repo, check=True, capture_output=True, text=True
    )


def _init_repo(repo: Path, *, with_origin_main: bool) -> None:
    """A repo whose 'main' branch sits one commit behind HEAD.

    HEAD's extra commit lands on a separate 'feature' branch, checked out
    from 'main' — the same topology a real PR branch has relative to a
    (possibly stale) local main ref, so a fallback to local main has a
    real, non-empty diff to find rather than comparing a branch against
    itself.
    """
    assert _GIT is not None
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "docs" / "review").mkdir(parents=True)
    (repo / "docs" / "review" / "adversarial.md").write_text("# rubric\n")
    # .review/ is git-ignored in the real repo, so the driver's own session and
    # artifact files under it do not dirty the tree it is reviewing.
    (repo / ".gitignore").write_text(".review/\n")
    (repo / "f.txt").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    base_sha = subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [_GIT, "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    if with_origin_main:
        # A remote-tracking ref, faked directly — the script only asks git
        # whether refs/remotes/origin/main resolves, so a real configured
        # remote isn't needed to exercise that check.
        _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)
    _git(repo, "checkout", "-qb", "feature")
    (repo / "f.txt").write_text("two\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")


def _resolved_base(stderr: str) -> str | None:
    match = re.search(r"review of HEAD vs '([^']*)'", stderr)
    return match.group(1) if match else None


def _run_review(tmp_path: Path, *, with_origin_main: bool, base_arg: str | None) -> str:
    """Run the review script; return the resolved base read off its stderr."""
    repo = tmp_path / "repo"
    _init_repo(repo, with_origin_main=with_origin_main)

    result = run_review(repo, tmp_path, "adversarial", base_arg)
    resolved = _resolved_base(result.stderr)
    assert resolved is not None, f"no resolved-base line in stderr:\n{result.stderr}"
    return resolved


def test_omitted_base_prefers_origin_main_when_known(tmp_path: Path) -> None:
    resolved = _run_review(tmp_path, with_origin_main=True, base_arg=None)
    assert resolved == "origin/main"


def test_omitted_base_falls_back_to_local_main_without_origin(tmp_path: Path) -> None:
    resolved = _run_review(tmp_path, with_origin_main=False, base_arg=None)
    assert resolved == "main"


def test_explicit_base_is_respected_even_with_origin_main_present(tmp_path: Path) -> None:
    resolved = _run_review(tmp_path, with_origin_main=True, base_arg="HEAD~1")
    assert resolved == "HEAD~1"
