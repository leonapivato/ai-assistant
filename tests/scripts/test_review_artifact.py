"""Tests that scripts/codex-review.sh records its review against a commit.

Review runs locally now (ADR-0015 §1), so the PR record depends on a human or
agent pasting it. The artifact is what makes that paste checkable: `just ship`
matches its filename SHA against the PR head, so a review of a stale commit is
caught mechanically rather than by care. These tests pin the two properties
`ship` relies on — the filename names the reviewed commit, and the body is
recoverable after the provenance header line.

Driven as a subprocess with a fake ``codex`` on ``PATH``, so no OpenAI call
happens.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).parents[2] / "scripts" / "codex-review.sh"
_BASH = shutil.which("bash")
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
    (repo / "f.txt").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "feature")
    (repo / "f.txt").write_text("two\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")
    return _git(repo, "rev-parse", "HEAD")


def _fake_codex(bin_dir: Path) -> None:
    """A fake ``codex`` that writes a stub review body to its ``-o`` file."""
    bin_dir.mkdir()
    codex = bin_dir / "codex"
    codex.write_text(
        "#!/usr/bin/env bash\n"
        'prev=""\n'
        'for a in "$@"; do\n'
        '  [[ "$prev" == "-o" ]] && printf "finding one\\nfinding two\\n" >"$a"\n'
        '  prev="$a"\n'
        "done\n"
    )
    codex.chmod(0o755)


def _run_review(repo: Path, tmp_path: Path, persona: str = "adversarial") -> None:
    assert _BASH is not None
    env = os.environ.copy()
    env.pop("GITHUB_ACTIONS", None)
    env.pop("CODEX_REVIEW_NO_SANDBOX", None)
    env["PATH"] = f"{tmp_path / 'bin'}{os.pathsep}{env['PATH']}"
    subprocess.run(  # noqa: S603  # resolved bash, in-repo script, test-controlled env
        [_BASH, str(_SCRIPT), persona, "main"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def test_review_is_recorded_under_the_reviewed_commit_sha(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_codex(tmp_path / "bin")

    _run_review(repo, tmp_path)

    assert (repo / ".review" / f"{sha}-adversarial.md").is_file()


def test_recorded_review_keeps_the_body_after_the_provenance_header(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_codex(tmp_path / "bin")

    _run_review(repo, tmp_path)

    lines = (repo / ".review" / f"{sha}-adversarial.md").read_text().splitlines()
    assert lines[0].startswith("<!--")
    assert sha in lines[0]
    # ship.sh strips exactly the first line; everything after it is the review.
    assert lines[1:] == ["finding one", "finding two"]


def test_each_persona_records_a_separate_artifact_for_one_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_codex(tmp_path / "bin")
    (repo / "docs" / "review" / "architecture.md").write_text("# rubric\n")

    _run_review(repo, tmp_path, "adversarial")
    _run_review(repo, tmp_path, "architecture")

    recorded = sorted(p.name for p in (repo / ".review").iterdir())
    assert recorded == [f"{sha}-adversarial.md", f"{sha}-architecture.md"]
