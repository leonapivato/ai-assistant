"""Tests for the CI sandbox-mode selection in scripts/codex-review.sh.

The adversarial review of the CI-sandbox fix (ADR-0012 §4 amendment) required
that Codex's own sandbox be dropped *only* in CI, keyed on the exact string
``GITHUB_ACTIONS == "true"`` — an inherited ``GITHUB_ACTIONS=false`` must not
silently disable the local read-only sandbox.

The script is driven as a subprocess with a fake ``codex`` on ``PATH`` that
records the arguments it receives, so the test asserts which sandbox flag the
script selects per environment, without contacting OpenAI.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _fake_codex import run_review

_GIT = shutil.which("git")

_BYPASS = "--dangerously-bypass-approvals-and-sandbox"


def _git(repo: Path, *args: str) -> None:
    assert _GIT is not None
    subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [_GIT, *args], cwd=repo, check=True, capture_output=True, text=True
    )


def _init_repo(repo: Path) -> str:
    """Create a two-commit repo with the adversarial rubric; return the base SHA."""
    assert _GIT is not None
    _git(repo, "init", "-q")
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
    base = subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [_GIT, "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    (repo / "f.txt").write_text("two\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")
    return base


def _run_review(tmp_path: Path, *, env_overrides: dict[str, str]) -> list[str]:
    """Run the review script in a temp repo; return the args the fake codex saw."""
    repo = tmp_path / "repo"
    repo.mkdir()
    base = _init_repo(repo)
    args_file = tmp_path / "codex-args.txt"

    run_review(
        repo,
        tmp_path,
        "adversarial",
        base,
        env={"FAKE_CODEX_ARGS_FILE": str(args_file), **env_overrides},
    )
    return args_file.read_text().splitlines()


@pytest.mark.parametrize(
    ("env_overrides", "expect_bypass"),
    [
        ({"GITHUB_ACTIONS": "true"}, True),  # CI runner: drop Codex's own sandbox
        ({}, False),  # local: keep the read-only sandbox
        ({"GITHUB_ACTIONS": "false"}, False),  # inherited false must NOT disable it
        ({"GITHUB_ACTIONS": "0"}, False),  # any non-"true" value stays local
        ({"CODEX_REVIEW_NO_SANDBOX": "1"}, True),  # explicit override
    ],
)
def test_sandbox_arg_selection(
    tmp_path: Path, env_overrides: dict[str, str], expect_bypass: bool
) -> None:
    args = _run_review(tmp_path, env_overrides=env_overrides)
    if expect_bypass:
        assert _BYPASS in args
        assert "read-only" not in args
    else:
        # "-s" and "read-only" are separate argv entries.
        assert "-s" in args
        assert "read-only" in args
        assert _BYPASS not in args
