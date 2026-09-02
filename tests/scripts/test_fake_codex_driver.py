"""The shared driver's own contract: it diagnoses, and it isolates.

``_fake_codex.run_review`` is what every module under ``tests/scripts`` drives
``scripts/codex-review.sh`` through. Properties of the driver itself — not of the
script — are pinned here: the first two because issue #1792 turned on both of
them, the third because the fix for it put a stub in the round's ``PATH`` whose
exit status the round then reads (#1825).

**It surfaces the script's own words.** ``subprocess.run(check=True)`` raises a
``CalledProcessError`` whose ``str()`` is the command line and the exit status;
the captured streams sit on the exception and pytest never renders them. Four
occurrences of #1792 were filed with no message attached for exactly that reason,
each one costing a reproduction to recover a sentence the script had already
printed.

**It keeps the operator's tools out of the subprocess.** ``review_env`` already
redirects ``CODEX_HOME`` and ``TMPDIR`` and clears the CI signals. ``gh`` belongs
in the same list, and its absence from it was the *cause* of #1792 rather than
merely its illegibility: ``gh pr view`` forks a detached ``gh send-telemetry``
child, which inherits the descriptor the round holds its in-flight ``flock`` on,
so the lock outlived the round and the next round in that repository was refused
as a concurrent one.

**And the stub fails the way the real one did.** ``codex-review.sh`` records the
PR description it was taken beside; a ``gh`` that succeeds with an empty body is
recorded as a snapshot of that empty body, not as no snapshot. The stub's
``exit 1`` is what keeps a round in this package honest about having no PR to
ask about.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _fake_codex import (
    ReviewFailed,
    install_fake_codex,
    require_artifact,
    review_env,
    run_review,
)
from _repo_template import seed_repo

_GIT = shutil.which("git")


def _git(repo: Path, *args: str) -> str:
    assert _GIT is not None
    return subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [_GIT, *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(repo: Path) -> str:
    """A minimal repository on a feature branch, reviewable by the script.

    Returns:
        The SHA of the feature commit a round reviews.
    """
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
    return _git(repo, "rev-parse", "HEAD")


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


def test_the_operators_gh_never_reaches_the_round(tmp_path: Path) -> None:
    """``gh`` resolves inside ``tmp_path``, so no real one is ever forked.

    Issue #1792: the real ``gh`` daemonizes a telemetry child that inherits the
    round's in-flight lock descriptor, and an ``flock`` lives on the open file
    description — so the lock outlives the round and the next one in that
    repository is refused. A round has no business calling the operator's ``gh``
    anyway; the repository under ``tmp_path`` has no remote to ask about.
    """
    env = review_env(tmp_path)

    resolved = shutil.which("gh", path=env["PATH"])

    assert resolved is not None, "the script's `command -v gh` guard must still find one"
    assert Path(resolved).is_relative_to(tmp_path), resolved


def test_a_test_installed_gh_outranks_the_stub(tmp_path: Path) -> None:
    """The stub sits behind ``tmp_path/"bin"``, which is where a test's own ``gh`` goes."""
    install_fake_codex(tmp_path / "bin")
    mine = tmp_path / "bin" / "gh"
    mine.write_text("#!/usr/bin/env bash\nexit 0\n")
    mine.chmod(0o755)

    resolved = shutil.which("gh", path=review_env(tmp_path)["PATH"])

    assert resolved == str(mine)


def test_a_round_under_the_stub_alone_records_no_description(tmp_path: Path) -> None:
    """The stub's ``exit 1`` is a required semantic, pinned where it is observable.

    Issue #1825. The stub stands in for the operator's ``gh``, which had nothing to
    answer here anyway — the repository under ``tmp_path`` has no remote. What makes
    *how* it fails load-bearing is what `codex-review.sh` does with a successful
    read: it hashes the body it got and records that hash as ``pr_desc``. A stub
    that regressed to ``exit 0`` answers with an **empty** body, whose SHA-1
    (``da39a3ee…``) is a perfectly well-formed 40-hex name — so every round in this
    package would start recording a description snapshot for a body no PR has, and
    `ship` would read that empty snapshot as ADR-0209 §5 text this branch had.

    Nothing else catches that. ``test_the_operators_gh_never_reaches_the_round``
    asserts only where ``gh`` resolves, and the one test that asserts
    ``pr_desc=unavailable``
    (``test_review_artifact.py::test_a_description_that_cannot_be_read_is_recorded_as_unavailable``)
    installs a failing ``gh`` of its own in ``tmp_path/"bin"``, which outranks the
    stub — so it would pass over a stub that had stopped failing. This round runs
    with the shipped stub as the *only* ``gh`` on ``PATH``, which is the default
    every other module here drives.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)

    run_review(repo, tmp_path)

    header = require_artifact(repo, sha).read_text().splitlines()[0]
    assert " pr_desc=unavailable " in header, header
    # No snapshot either: the field and the directory have to agree, or `ship`
    # would be reading a body against an artifact that never claimed one.
    snapshots = repo / ".review" / "descriptions"
    assert not snapshots.exists() or not any(snapshots.iterdir())
