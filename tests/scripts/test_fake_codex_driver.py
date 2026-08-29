"""The shared driver's own contract: a failing round diagnoses itself.

``_fake_codex.run_review`` is what every module under ``tests/scripts`` drives
``scripts/codex-review.sh`` through, so what it does with a non-zero exit decides
whether a failure in any of them is readable.

``subprocess.run(check=True)`` raises a
``CalledProcessError`` whose ``str()`` is the command line and the exit status;
the captured streams sit on the exception and pytest never renders them. Four
occurrences of #1792 were filed with no message attached for exactly that reason,
each one costing a reproduction to recover a sentence the script had already
printed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _fake_codex import ReviewFailed, run_review
from _repo_template import seed_repo

_GIT = shutil.which("git")


def _git(repo: Path, *args: str) -> None:
    assert _GIT is not None
    subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [_GIT, *args], cwd=repo, check=True, capture_output=True, text=True
    )


def _init_repo(repo: Path) -> None:
    """A minimal repository on a feature branch, reviewable by the script."""
    repo.mkdir(parents=True)
    seed_repo(repo)
    (repo / "docs" / "review").mkdir(parents=True)
    (repo / "docs" / "review" / "adversarial.md").write_text("# rubric\n")
    (repo / ".gitignore").write_text(".review/\n")
    (repo / "f.txt").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "feature")
    (repo / "f.txt").write_text("two\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")


def test_a_refused_round_raises_with_the_scripts_own_stderr(tmp_path: Path) -> None:
    """The reason the script printed is in the message, not only on the exception.

    Driven through the fail-closed sandbox proof, which is a refusal the script
    states in one sentence — so what is asserted is that *that sentence* reaches a
    reader of the failure, which is the whole of what #1792 was missing.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)

    with pytest.raises(ReviewFailed) as raised:
        run_review(repo, tmp_path, FAKE_CODEX_FORCE_SANDBOX="danger-full-access")

    rendered = str(raised.value)
    assert "returned non-zero exit status 1" in rendered
    assert "could not prove the review ran read-only" in rendered
    # Both streams are named, so an empty one reads as "the script said nothing
    # here" rather than as the driver having dropped it.
    assert "stderr (the script's own diagnosis)" in rendered
    assert "stdout" in rendered


def test_the_failure_is_still_a_called_process_error(tmp_path: Path) -> None:
    """Callers keep ``returncode``/``stdout``/``stderr`` and the type they catch."""
    repo = tmp_path / "repo"
    _init_repo(repo)

    with pytest.raises(subprocess.CalledProcessError) as raised:
        run_review(repo, tmp_path, FAKE_CODEX_FORCE_SANDBOX="danger-full-access")

    assert raised.value.returncode == 1
    assert "could not prove the review ran read-only" in raised.value.stderr


def test_check_false_still_returns_the_completed_process(tmp_path: Path) -> None:
    """The non-raising form is unchanged — the tests asserting on stderr rely on it."""
    repo = tmp_path / "repo"
    _init_repo(repo)

    result = run_review(repo, tmp_path, check=False, FAKE_CODEX_FORCE_SANDBOX="danger-full-access")

    assert result.returncode == 1
    assert "could not prove the review ran read-only" in result.stderr
