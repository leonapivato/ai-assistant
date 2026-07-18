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

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[2] / "scripts" / "codex-review.sh"
_BASH = shutil.which("bash")
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


def _fake_codex(bin_dir: Path, args_file: Path) -> None:
    """Install a fake ``codex`` that records its args and writes the ``-o`` file."""
    bin_dir.mkdir()
    codex = bin_dir / "codex"
    codex.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$@" >"{args_file}"\n'
        'prev=""\n'
        'for a in "$@"; do\n'
        '  [[ "$prev" == "-o" ]] && printf "review body\\n" >"$a"\n'
        '  prev="$a"\n'
        "done\n"
    )
    codex.chmod(0o755)


def _run_review(tmp_path: Path, *, env_overrides: dict[str, str]) -> list[str]:
    """Run the review script in a temp repo; return the args the fake codex saw."""
    assert _BASH is not None
    repo = tmp_path / "repo"
    repo.mkdir()
    base = _init_repo(repo)
    args_file = tmp_path / "codex-args.txt"
    _fake_codex(tmp_path / "bin", args_file)

    env = os.environ.copy()
    # Control the CI signal explicitly — the test itself may run under Actions.
    env.pop("GITHUB_ACTIONS", None)
    env.pop("CODEX_REVIEW_NO_SANDBOX", None)
    env["PATH"] = f"{tmp_path / 'bin'}{os.pathsep}{env['PATH']}"
    env.update(env_overrides)

    subprocess.run(  # noqa: S603  # resolved bash, in-repo script, test-controlled env
        [_BASH, str(_SCRIPT), "adversarial", base],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
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
