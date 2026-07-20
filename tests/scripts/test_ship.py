"""Tests for scripts/ship.sh — the merge-readiness step (ADR-0015 §1).

With review no longer running in CI, `ship` is the only thing standing between
"a review happened" and "the review on the PR covers the code being merged".
Its refusals are the mechanism the ADR trades the CI-posted record for, so each
one is pinned here: a review of a different commit, an unpushed HEAD, a dirty
tree, and a missing adversarial lens must all fail *closed* rather than post a
misleading record.

Driven as a subprocess with a fake ``gh`` on ``PATH``, so nothing reaches
GitHub.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).parents[2] / "scripts" / "ship.sh"
_BASH = shutil.which("bash")
_GIT = shutil.which("git")


def _git(repo: Path, *args: str) -> str:
    assert _GIT is not None
    return subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [_GIT, *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(repo: Path, *, touches_core: bool = False) -> str:
    """A repo on a feature branch, with an `origin` holding `main`.

    A real remote is needed because ship.sh fetches the PR's base branch to
    decide whether the diff touches the shared contract surface. ``touches_core``
    puts the change in ``core/protocols.py`` instead of an ordinary file, which
    is what should demand the architecture lens.
    """
    origin = repo.parent / "origin.git"
    subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [str(_GIT), "init", "-q", "--bare", "-b", "main", str(origin)], check=True
    )
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "f.txt").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "main")

    _git(repo, "checkout", "-qb", "feature")
    if touches_core:
        core = repo / "src" / "ai_assistant" / "core"
        core.mkdir(parents=True)
        (core / "protocols.py").write_text("class Thing: ...\n")
    else:
        (repo / "f.txt").write_text("two\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")
    return _git(repo, "rev-parse", "HEAD")


def _fake_gh(bin_dir: Path) -> None:
    """A fake ``gh`` answering the three calls ship.sh makes.

    ``GH_PR_SHA`` is what the PR head reports; ``GH_COMMENT_OUT`` is where a
    posted comment body is captured so a test can assert on it.
    """
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "pr" && "$2" == "view" ]]; then\n'
        '  for a in "$@"; do\n'
        '    case "$a" in\n'
        '      headRefOid) printf "%s\\n" "$GH_PR_SHA"; exit 0 ;;\n'
        "      number) printf '42\\n'; exit 0 ;;\n"
        "      baseRefName) printf 'main\\n'; exit 0 ;;\n"
        "    esac\n"
        "  done\n"
        "fi\n"
        'if [[ "$1" == "pr" && "$2" == "comment" ]]; then\n'
        '  prev=""\n'
        '  for a in "$@"; do\n'
        '    [[ "$prev" == "--body-file" ]] && cp "$a" "$GH_COMMENT_OUT"\n'
        '    prev="$a"\n'
        "  done\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    )
    gh.chmod(0o755)


def _record_review(repo: Path, sha: str, persona: str, body: str = "a finding\n") -> None:
    review_dir = repo / ".review"
    review_dir.mkdir(exist_ok=True)
    (review_dir / f"{sha}-{persona}.md").write_text(f"<!-- sha={sha} -->\n{body}")


def _run_ship(repo: Path, tmp_path: Path, *, pr_sha: str) -> subprocess.CompletedProcess[str]:
    assert _BASH is not None
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path / 'bin'}{os.pathsep}{env['PATH']}"
    env["GH_PR_SHA"] = pr_sha
    env["GH_COMMENT_OUT"] = str(tmp_path / "comment.md")
    return subprocess.run(  # noqa: S603  # resolved bash, in-repo script, test-controlled env
        [_BASH, str(_SCRIPT)],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_posts_the_review_when_it_matches_the_pr_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", "a real finding\n")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "a real finding" in posted
    assert sha[:12] in posted
    # The provenance header is script metadata, not something a reader wants.
    assert "<!-- sha=" not in posted


def test_refuses_when_the_review_covers_a_different_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    # A review of the *previous* commit — the exact stale-paste this guards.
    _record_review(repo, _git(repo, "rev-parse", "HEAD~1"), "adversarial")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "no adversarial review" in result.stderr
    assert "do not cover" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_refuses_when_the_pr_head_is_behind_local_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")

    result = _run_ship(repo, tmp_path, pr_sha=_git(repo, "rev-parse", "HEAD~1"))

    assert result.returncode != 0
    assert "push first" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_refuses_on_a_dirty_working_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")
    (repo / "f.txt").write_text("uncommitted\n")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "dirty" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_refuses_when_only_the_architecture_lens_was_run(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "architecture")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "no adversarial review" in result.stderr


def test_posts_every_persona_recorded_for_the_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", "adversarial finding\n")
    _record_review(repo, sha, "architecture", "architecture finding\n")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "adversarial finding" in posted
    assert "architecture finding" in posted


def test_refuses_a_core_change_without_the_architecture_lens(tmp_path: Path) -> None:
    """A contract change needs both lenses — previously documented, not checked."""
    repo = tmp_path / "repo"
    sha = _init_repo(repo, touches_core=True)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "architecture" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_posts_a_core_change_carrying_both_lenses(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo, touches_core=True)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")
    _record_review(repo, sha, "architecture")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "comment.md").exists()


def test_a_non_core_change_needs_only_the_adversarial_lens(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr


def test_refuses_on_main(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _git(repo, "checkout", "-q", "main")

    result = _run_ship(repo, tmp_path, pr_sha=_git(repo, "rev-parse", "HEAD"))

    assert result.returncode != 0
    assert "on main" in result.stderr
