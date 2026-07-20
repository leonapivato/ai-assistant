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


def _fake_codex(bin_dir: Path) -> None:
    """A fake ``codex`` that writes a stub review body to its ``-o`` file."""
    bin_dir.mkdir()
    codex = bin_dir / "codex"
    codex.write_text(
        "#!/usr/bin/env bash\n"
        'prev=""\n'
        'for a in "$@"; do\n'
        # A verdict line is part of the rubric's output contract, and the script
        # now requires one — a fake without it would be rejected as a refusal.
        '  [[ "$prev" == "-o" ]] && printf "finding one\\nfinding two\\n'
        'Verdict: APPROVE\\n" >"$a"\n'
        '  prev="$a"\n'
        "done\n"
    )
    codex.chmod(0o755)


def _run_review(
    repo: Path, tmp_path: Path, persona: str = "adversarial", *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    assert _BASH is not None
    env = os.environ.copy()
    env.pop("GITHUB_ACTIONS", None)
    env.pop("CODEX_REVIEW_NO_SANDBOX", None)
    env["PATH"] = f"{tmp_path / 'bin'}{os.pathsep}{env['PATH']}"
    return subprocess.run(  # noqa: S603  # resolved bash, in-repo script, test-controlled env
        [_BASH, str(_SCRIPT), persona, "main"],
        cwd=repo,
        check=check,
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
    assert lines[1:] == ["finding one", "finding two", "Verdict: APPROVE"]


def test_empty_codex_output_is_refused_rather_than_recorded(tmp_path: Path) -> None:
    """An empty artifact would read to ship.sh as a completed, clean review."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # codex exits 0 but writes nothing — a dropped connection or a refusal.
    codex = bin_dir / "codex"
    codex.write_text(
        "#!/usr/bin/env bash\n"
        'prev=""\n'
        'for a in "$@"; do\n'
        '  [[ "$prev" == "-o" ]] && : >"$a"\n'
        '  prev="$a"\n'
        "done\n"
    )
    codex.chmod(0o755)

    result = _run_review(repo, tmp_path, check=False)

    assert result.returncode != 0
    assert "empty review" in result.stderr
    assert not (repo / ".review").exists()


def test_whitespace_only_codex_output_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    codex = bin_dir / "codex"
    codex.write_text(
        "#!/usr/bin/env bash\n"
        'prev=""\n'
        'for a in "$@"; do\n'
        '  [[ "$prev" == "-o" ]] && printf "  \\n\\n" >"$a"\n'
        '  prev="$a"\n'
        "done\n"
    )
    codex.chmod(0o755)

    result = _run_review(repo, tmp_path, check=False)

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
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # A fake codex that commits to the repo while "reviewing" — the race the
    # pinning exists to close, made deterministic.
    codex = bin_dir / "codex"
    codex.write_text(
        "#!/usr/bin/env bash\n"
        'printf "later\\n" >>f.txt\n'
        "git add f.txt\n"
        'git commit -qm "landed mid-review"\n'
        'prev=""\n'
        'for a in "$@"; do\n'
        '  [[ "$prev" == "-o" ]] && printf "finding\\n" >"$a"\n'
        '  prev="$a"\n'
        "done\n"
    )
    codex.chmod(0o755)

    result = _run_review(repo, tmp_path, check=False)

    moved_sha = _git(repo, "rev-parse", "HEAD")
    assert moved_sha != reviewed_sha, "fake codex should have advanced HEAD"
    assert result.returncode != 0
    assert "changed while the review was running" in result.stderr
    # Neither SHA gets an artifact: the run is void, not merely misfiled.
    assert not (repo / ".review" / f"{reviewed_sha}-adversarial.md").exists()
    assert not (repo / ".review" / f"{moved_sha}-adversarial.md").exists()


def test_a_refusal_without_a_verdict_is_not_recorded_as_a_review(tmp_path: Path) -> None:
    """Non-empty prose is not a review; the rubric requires a closing verdict."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    codex = bin_dir / "codex"
    codex.write_text(
        "#!/usr/bin/env bash\n"
        'prev=""\n'
        'for a in "$@"; do\n'
        '  [[ "$prev" == "-o" ]] && printf "I am unable to review this repository.\\n" >"$a"\n'
        '  prev="$a"\n'
        "done\n"
    )
    codex.chmod(0o755)

    result = _run_review(repo, tmp_path, check=False)

    assert result.returncode != 0
    assert "no verdict" in result.stderr
    assert not (repo / ".review").exists()


def test_refuses_to_review_a_dirty_tree(tmp_path: Path) -> None:
    """Codex reads the working tree for context, so it must match the commit."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _fake_codex(tmp_path / "bin")
    (repo / "f.txt").write_text("uncommitted context\n")

    result = _run_review(repo, tmp_path, check=False)

    assert result.returncode != 0
    assert "dirty" in result.stderr
    assert not (repo / ".review").exists()


def test_each_persona_records_a_separate_artifact_for_one_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_codex(tmp_path / "bin")

    _run_review(repo, tmp_path, "adversarial")
    _run_review(repo, tmp_path, "architecture")

    recorded = sorted(p.name for p in (repo / ".review").iterdir())
    assert recorded == [f"{sha}-adversarial.md", f"{sha}-architecture.md"]
