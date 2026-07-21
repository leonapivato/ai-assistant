"""Tests that scripts/codex-review.sh records its review against a commit.

Review runs locally now (ADR-0015 §1), so the PR record depends on a human or
agent pasting it. The artifact is what makes that paste checkable: `just ship`
matches its filename SHA against the PR head, so a review of a stale commit is
caught mechanically rather than by care. These tests pin the two properties
`ship` relies on — the filename names the reviewed commit, and the body is
recoverable after the provenance header line.

Driven as a subprocess with a fake ``codex`` (see ``_fake_codex``) that emits the
``--json`` thread stream and writes a read-only session rollout, so the
persistent-session driver's read-only proof (ADR-0025) is satisfied without an
OpenAI call.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _fake_codex import run_review

_GIT = shutil.which("git")


def _git(repo: Path, *args: str) -> str:
    assert _GIT is not None
    return subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [_GIT, *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(repo: Path) -> str:
    """A repo with a feature commit on top of main; returns the HEAD SHA."""
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "docs" / "review").mkdir(parents=True)
    (repo / "docs" / "review" / "adversarial.md").write_text("# rubric\n")
    (repo / "docs" / "review" / "architecture.md").write_text("# rubric\n")
    # Mirrors the real repo: .review/ is ignored, so the clean-tree check the
    # script now makes does not trip on the artifacts it writes itself.
    (repo / ".gitignore").write_text(".review/\n")
    (repo / "f.txt").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "feature")
    (repo / "f.txt").write_text("two\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")
    return _git(repo, "rev-parse", "HEAD")


def _private_tmpdir(tmp_path: Path) -> Path:
    """The temp directory the script under test is pointed at (``review_env``)."""
    private = tmp_path / "tmp"
    private.mkdir(exist_ok=True)
    return private


def test_review_is_recorded_under_the_reviewed_commit_sha(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)

    run_review(repo, tmp_path)

    assert (repo / ".review" / f"{sha}-adversarial.md").is_file()


def test_recorded_review_keeps_the_body_after_the_provenance_header(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)

    run_review(repo, tmp_path, FAKE_CODEX_REVIEW="finding one\nfinding two\nVerdict: APPROVE\n")

    lines = (repo / ".review" / f"{sha}-adversarial.md").read_text().splitlines()
    assert lines[0].startswith("<!--")
    assert sha in lines[0]
    # ship.sh strips exactly the first line; everything after it is the review.
    assert lines[1:] == ["finding one", "finding two", "Verdict: APPROVE"]


def test_empty_codex_output_is_refused_rather_than_recorded(tmp_path: Path) -> None:
    """An empty artifact would read to ship.sh as a completed, clean review."""
    repo = tmp_path / "repo"
    _init_repo(repo)

    result = run_review(repo, tmp_path, check=False, FAKE_CODEX_REVIEW="")

    assert result.returncode != 0
    assert "empty review" in result.stderr
    assert not (repo / ".review" / f"{_git(repo, 'rev-parse', 'HEAD')}-adversarial.md").exists()


def test_whitespace_only_codex_output_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    result = run_review(repo, tmp_path, check=False, FAKE_CODEX_REVIEW="  \n\n")

    assert result.returncode != 0
    assert "empty review" in result.stderr


def test_records_nothing_when_the_checkout_moves_mid_review(tmp_path: Path) -> None:
    """A commit landing mid-review invalidates the run, rather than being filed.

    Pinning the diff is necessary but not sufficient: Codex also reads the
    working tree, so a checkout that moves underneath it produces a review of
    a tree that matches neither SHA. Recording that under the pinned SHA would
    be a false record — worse than no record, since ship.sh would accept it.
    """
    repo = tmp_path / "repo"
    reviewed_sha = _init_repo(repo)
    # The fake commits to the repo while "reviewing" — the race the pinning
    # exists to close, made deterministic.
    pre = 'printf "later\\n" >>f.txt; git add f.txt; git commit -qm "landed mid-review"'

    result = run_review(repo, tmp_path, check=False, FAKE_CODEX_PRE_CMD=pre)

    moved_sha = _git(repo, "rev-parse", "HEAD")
    assert moved_sha != reviewed_sha, "fake codex should have advanced HEAD"
    assert result.returncode != 0
    assert "changed while the review was running" in result.stderr
    assert not (repo / ".review" / f"{reviewed_sha}-adversarial.md").exists()
    assert not (repo / ".review" / f"{moved_sha}-adversarial.md").exists()


def test_a_refusal_without_a_verdict_is_not_recorded_as_a_review(tmp_path: Path) -> None:
    """Non-empty prose is not a review; the rubric requires a closing verdict."""
    repo = tmp_path / "repo"
    _init_repo(repo)

    result = run_review(
        repo, tmp_path, check=False, FAKE_CODEX_REVIEW="I am unable to review this repository.\n"
    )

    assert result.returncode != 0
    assert "does not end in a verdict" in result.stderr
    assert not (repo / ".review" / f"{_git(repo, 'rev-parse', 'HEAD')}-adversarial.md").exists()


def test_a_verdict_with_no_review_body_is_not_recorded(tmp_path: Path) -> None:
    """A rubber stamp is a failure by the rubric's own anti-patterns.

    Both spellings are refused: dropping the ``Verdict:`` label let the bare form
    through, but the labelled form always passed, so the hole predates that.
    """
    for i, output in enumerate(("APPROVE\n", "Verdict: APPROVE\n")):
        repo = tmp_path / f"repo-{i}"
        _init_repo(repo)

        result = run_review(repo, tmp_path, check=False, FAKE_CODEX_REVIEW=output)

        assert result.returncode != 0, f"{output!r} was recorded"
        assert "no review body" in result.stderr


def test_prose_mentioning_a_verdict_is_not_accepted_as_one(tmp_path: Path) -> None:
    """A substring search would pass this; the check is anchored for that reason."""
    repo = tmp_path / "repo"
    _init_repo(repo)

    result = run_review(
        repo,
        tmp_path,
        check=False,
        FAKE_CODEX_REVIEW="I cannot provide a verdict or APPROVE this change.\n",
    )

    assert result.returncode != 0
    assert "does not end in a verdict" in result.stderr


def test_accepts_the_verdict_forms_the_reviewer_actually_emits(tmp_path: Path) -> None:
    """Observed in real output: bold, all-caps, and plain, with and without nits."""
    for i, form in enumerate(
        (
            "**Verdict: APPROVE WITH NITS**",
            "VERDICT: BLOCK",
            "Verdict: APPROVE",
            "APPROVE WITH NITS",
            "**APPROVE**",
            "BLOCK",
        )
    ):
        repo = tmp_path / f"repo-{i}"
        _init_repo(repo)

        result = run_review(repo, tmp_path, check=False, FAKE_CODEX_REVIEW=f"a finding\n\n{form}\n")

        assert result.returncode == 0, f"{form!r} rejected: {result.stderr}"


def test_leaves_no_temporary_files_behind(tmp_path: Path) -> None:
    """Review text must not accumulate in the temp dir or as .partial files."""
    repo = tmp_path / "repo"
    sha = _init_repo(repo)

    run_review(repo, tmp_path)

    assert list(_private_tmpdir(tmp_path).iterdir()) == []
    # The artifact is present; session/ and dispositions/ subdirs are expected
    # alongside it now (ADR-0025), so this checks for the artifact, not exclusivity.
    assert (repo / ".review" / f"{sha}-adversarial.md").is_file()
    assert not list((repo / ".review").glob("*.partial.*"))


def test_refuses_to_review_a_dirty_tree(tmp_path: Path) -> None:
    """Codex reads the working tree for context, so it must match the commit."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "f.txt").write_text("uncommitted context\n")

    result = run_review(repo, tmp_path, check=False)

    assert result.returncode != 0
    assert "dirty" in result.stderr
    assert not (repo / ".review").exists()


def test_records_the_base_it_reviewed_when_the_base_ref_moves(tmp_path: Path) -> None:
    """The left edge of the range is pinned too, not just HEAD."""
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    reviewed_base = _git(repo, "merge-base", "main", sha)
    # The fake advances `main` while "reviewing", without touching feature's HEAD.
    pre = (
        "git branch -f main-tmp main >/dev/null 2>&1; "
        'git commit -q --allow-empty -m "base moved" >/dev/null 2>&1; '
        "git branch -f main HEAD >/dev/null 2>&1; "
        "git reset -q --hard HEAD~1"
    )

    run_review(repo, tmp_path, FAKE_CODEX_PRE_CMD=pre)

    assert _git(repo, "rev-parse", "main") != reviewed_base, "fake should have moved main"
    header = (repo / ".review" / f"{sha}-adversarial.md").read_text().splitlines()[0]
    assert f"base_sha={reviewed_base}" in header


def test_each_persona_records_a_separate_artifact_for_one_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)

    run_review(repo, tmp_path, "adversarial")
    run_review(repo, tmp_path, "architecture")

    recorded = sorted(p.name for p in (repo / ".review").glob("*.md"))
    assert recorded == [f"{sha}-adversarial.md", f"{sha}-architecture.md"]
