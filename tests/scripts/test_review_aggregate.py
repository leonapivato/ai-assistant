"""Tests for the per-run preamble and the printed aggregate (ADR-0020 §1, §2).

Two mechanisms are pinned here.

**The preamble (§1)** tells the reviewer what it is reading. Adversarial review
applies a code rubric, and its findings about illustrative snippets in prose are
noise — but the exemption must *not* extend to a normative snippet, because a
fenced block can be the decision itself (ADR-0016 defines the ``ToolRegistry``
Protocol in one). Getting that distinction wrong is the whole risk in §1, so the
tests below check both halves are stated, and that the prose half is omitted
entirely on a code-only change rather than asserted where it is false.

**The aggregate (§2)** is the number that makes a runaway loop legible. It
blocks nothing — deliberately; a round cap would have forbidden the round of #90
that found ``gh pr merge --match-head-commit`` — so what is testable is that it
is computed correctly and always emitted.

Driven as a subprocess with a fake ``codex`` on ``PATH``, so no OpenAI call
happens.
"""

from __future__ import annotations

import os
import re
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


def _init_repo(repo: Path) -> None:
    """A repo on a feature branch, with `docs/adr/` present for the size lookup."""
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "docs" / "review").mkdir(parents=True)
    (repo / "docs" / "review" / "adversarial.md").write_text("# rubric\n")
    (repo / "docs" / "review" / "architecture.md").write_text("# rubric\n")
    (repo / "docs" / "adr").mkdir(parents=True)
    # A 175-line ADR, the size of the real ADR-0004 — the document ADR-0017
    # superseded one clause of while growing to 821 lines itself.
    (repo / "docs" / "adr" / "0004-privacy.md").write_text("line\n" * 175)
    (repo / ".gitignore").write_text(".review/\n")
    (repo / "f.txt").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "feature")


def _fake_codex(bin_dir: Path, prompt_copy: Path) -> None:
    """A fake ``codex`` that saves the prompt it was given and emits a verdict.

    The prompt is what carries the §1 preamble, so capturing it is the only way
    to assert on what the reviewer was actually told.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    codex = bin_dir / "codex"
    codex.write_text(
        "#!/usr/bin/env bash\n"
        'prev=""\n'
        'for a in "$@"; do\n'
        '  [[ "$prev" == "-o" ]] && printf "a finding\\nVerdict: APPROVE\\n" >"$a"\n'
        '  prev="$a"\n'
        "done\n"
        # codex-review.sh feeds the prompt on stdin (`codex exec ... - <"$prompt"`).
        f'cat >"{prompt_copy}"\n'
    )
    codex.chmod(0o755)


def _run(
    repo: Path, tmp_path: Path, persona: str = "adversarial", *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    assert _BASH is not None
    env = os.environ.copy()
    env.pop("GITHUB_ACTIONS", None)
    env.pop("CODEX_REVIEW_NO_SANDBOX", None)
    env["PATH"] = f"{tmp_path / 'bin'}{os.pathsep}{env['PATH']}"
    private_tmp = tmp_path / "tmp"
    private_tmp.mkdir(exist_ok=True)
    env["TMPDIR"] = str(private_tmp)
    return subprocess.run(  # noqa: S603  # resolved bash, in-repo script, test-controlled env
        [_BASH, str(_SCRIPT), persona, "main"],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


def _provenance(repo: Path) -> str:
    """The single provenance line of the one artifact recorded."""
    artifacts = sorted((repo / ".review").iterdir())
    assert len(artifacts) == 1, f"expected one artifact, got {artifacts}"
    return artifacts[0].read_text().splitlines()[0]


def _field(provenance: str, name: str) -> str | None:
    match = re.search(rf"\b{name}=(\S+?)(?=\s|-->)", provenance)
    return match.group(1) if match else None


def _commit(repo: Path, path: str, content: str, message: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


# --- §1: what the reviewer is told it is reading -----------------------------


def test_prose_change_tells_the_reviewer_snippets_are_illustrative(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "docs/adr/0020-thing.md", "# 20. A decision\n\n```bash\nls\n```\n", "adr")
    _fake_codex(tmp_path / "bin", tmp_path / "prompt.txt")

    _run(repo, tmp_path)

    prompt = (tmp_path / "prompt.txt").read_text()
    assert "docs/adr/0020-thing.md" in prompt
    assert "illustrative" in prompt
    assert "mislead" in prompt
    # The specific judgments the code rubric would otherwise import wholesale.
    # Matched on unwrapped phrases: the preamble is hard-wrapped, so a longer
    # quotation would fail on the line break rather than on the content.
    assert "test coverage" in prompt
    assert "runtime correctness" in prompt


def test_the_exemption_is_explicitly_withheld_from_normative_snippets(tmp_path: Path) -> None:
    """The main risk in §1: a fenced block can *be* the decision.

    ADR-0016 defines the ``ToolRegistry`` Protocol in one, and ADR-0015 §5
    requires exactly that class of ADR to carry the architecture lens. A
    preamble that exempted a file type wholesale would tell the reviewer to skip
    the contract it is most needed on.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "docs/adr/0020-thing.md", "# 20. A decision\n\n```python\nx = 1\n```\n", "adr")
    _fake_codex(tmp_path / "bin", tmp_path / "prompt.txt")

    _run(repo, tmp_path)

    prompt = (tmp_path / "prompt.txt").read_text()
    assert "does not extend to a normative snippet" in prompt
    assert "per block, not per file" in prompt
    # The reviewer is told which way to fail when a block is ambiguous.
    assert "review it as normative" in prompt


def test_a_code_only_change_is_not_told_anything_about_prose(tmp_path: Path) -> None:
    """The qualification is per-run data precisely so it is absent where false.

    A rubric edit would apply it unconditionally; that is the reason ADR-0020 §1
    puts it in the invocation instead.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "scripts/thing.sh", "#!/usr/bin/env bash\necho hi\n", "code")
    _fake_codex(tmp_path / "bin", tmp_path / "prompt.txt")

    _run(repo, tmp_path)

    prompt = (tmp_path / "prompt.txt").read_text()
    assert "scripts/thing.sh" in prompt
    assert "illustrative" not in prompt
    assert "normative snippet" not in prompt


def test_a_txt_file_is_classified_as_code_not_prose(tmp_path: Path) -> None:
    """`.txt` is as likely machine-consumed as read, so it gets no exemption.

    The two misclassifications are not symmetric: calling prose "code" costs a
    few noisy findings, calling code "prose" waives the scrutiny it needs.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "requirements.txt", "pydantic==2.0\n", "reqs")
    _fake_codex(tmp_path / "bin", tmp_path / "prompt.txt")

    _run(repo, tmp_path)

    prompt = (tmp_path / "prompt.txt").read_text()
    assert "requirements.txt" in prompt
    assert "illustrative" not in prompt


def test_a_mixed_change_lists_both_kinds_separately(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "docs" / "adr" / "0020-thing.md").write_text("# 20. A decision\n")
    (repo / "scripts").mkdir(exist_ok=True)
    (repo / "scripts" / "thing.sh").write_text("#!/usr/bin/env bash\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "both")
    _fake_codex(tmp_path / "bin", tmp_path / "prompt.txt")

    _run(repo, tmp_path)

    prompt = (tmp_path / "prompt.txt").read_text()
    prose_block = prompt.split("**Prose**")[1].split("**Code, scripts")[0]
    assert "docs/adr/0020-thing.md" in prose_block
    assert "scripts/thing.sh" not in prose_block
    # And the prose qualification is present, since prose is genuinely involved.
    assert "illustrative" in prompt


# --- §2: the aggregate -------------------------------------------------------


def test_the_aggregate_is_printed_without_being_asked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "f.txt", "two\n", "change")
    _fake_codex(tmp_path / "bin", tmp_path / "prompt.txt")

    result = _run(repo, tmp_path)

    assert "aggregate (ADR-0020 §2)" in result.stderr
    assert "round" in result.stderr
    assert "churn ratio" in result.stderr


def test_churn_ratio_counts_rework_against_the_final_diff(tmp_path: Path) -> None:
    """Three commits rewriting one line: 3 lines touched per net line changed.

    This is the mechanical proxy for "consecutive commits fixing what the
    previous commit introduced" — no model and no judgment, only `--numstat`.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    # Each commit rewrites the same single line: 1 added + 1 deleted per commit
    # after the first, and the net diff is still just that one line.
    _commit(repo, "f.txt", "two\n", "c1")
    _commit(repo, "f.txt", "three\n", "c2")
    _commit(repo, "f.txt", "four\n", "c3")
    _fake_codex(tmp_path / "bin", tmp_path / "prompt.txt")

    _run(repo, tmp_path)

    provenance = _provenance(repo)
    assert _field(provenance, "net_lines") == "2", provenance
    assert _field(provenance, "churn_lines") == "6", provenance
    assert _field(provenance, "churn_ratio") == "3.0", provenance
    assert _field(provenance, "commits") == "3", provenance


def test_round_counts_commits_on_the_branch_already_carrying_a_review(tmp_path: Path) -> None:
    """Round 1 on a fresh branch; each already-reviewed ancestor adds one."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "f.txt", "two\n", "c1")
    _fake_codex(tmp_path / "bin", tmp_path / "prompt.txt")

    _run(repo, tmp_path)
    assert _field(_provenance(repo), "round") == "1"

    # A second commit: the first now carries an artifact, so this is round 2.
    _commit(repo, "f.txt", "three\n", "c2")
    _run(repo, tmp_path)
    second = (repo / ".review" / f"{_git(repo, 'rev-parse', 'HEAD')}-adversarial.md").read_text()
    assert _field(second.splitlines()[0], "round") == "2"


def test_a_second_persona_on_one_commit_stays_the_same_round(tmp_path: Path) -> None:
    """A round is a commit reviewed, not a review run.

    HEAD is skipped when counting, so running the architecture lens after the
    adversarial one on the same commit does not inflate the number.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "f.txt", "two\n", "c1")
    _fake_codex(tmp_path / "bin", tmp_path / "prompt.txt")

    _run(repo, tmp_path, "adversarial")
    _run(repo, tmp_path, "architecture")

    sha = _git(repo, "rev-parse", "HEAD")
    adversarial = (repo / ".review" / f"{sha}-adversarial.md").read_text().splitlines()[0]
    architecture = (repo / ".review" / f"{sha}-architecture.md").read_text().splitlines()[0]
    assert _field(adversarial, "round") == "1"
    assert _field(architecture, "round") == "1"


def test_records_the_size_of_a_document_the_change_supersedes(tmp_path: Path) -> None:
    """One number next to another is what made two hours of drift legible.

    ADR-0017 superseded a single clause of a 175-line ADR and peaked at 821
    lines; nobody inside the loop could see that.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(
        repo,
        "docs/adr/0020-thing.md",
        "# 20. A decision\n\n- Supersedes: ADR-0004 §2's egress clause\n",
        "adr",
    )
    _fake_codex(tmp_path / "bin", tmp_path / "prompt.txt")

    result = _run(repo, tmp_path)

    assert _field(_provenance(repo), "supersedes") == "ADR-0004:175"
    assert "ADR-0004 (175 lines)" in result.stderr


def test_an_unchanged_mention_of_supersedes_is_not_counted(tmp_path: Path) -> None:
    """Read off the *added* lines only, or every later edit re-reports it."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(
        repo,
        "docs/adr/0020-thing.md",
        "# 20. A decision\n\n- Supersedes: ADR-0004 §2's egress clause\n",
        "adr",
    )
    _git(repo, "checkout", "-qb", "later", "HEAD")
    _git(repo, "branch", "-f", "main", "HEAD")
    # A change that touches the file but not its Supersedes line.
    _commit(
        repo,
        "docs/adr/0020-thing.md",
        "# 20. A decision\n\n- Supersedes: ADR-0004 §2's egress clause\n\nMore body.\n",
        "expand",
    )
    _fake_codex(tmp_path / "bin", tmp_path / "prompt.txt")

    _run(repo, tmp_path)

    assert _field(_provenance(repo), "supersedes") is None


def test_the_aggregate_does_not_block_a_high_churn_change(tmp_path: Path) -> None:
    """Nothing here gates. A round cap would have cost #90 its best finding."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    for i in range(12):
        _commit(repo, "f.txt", f"rev {i}\n", f"c{i}")
    _fake_codex(tmp_path / "bin", tmp_path / "prompt.txt")

    result = _run(repo, tmp_path, check=False)

    assert result.returncode == 0, result.stderr
    provenance = _provenance(repo)
    assert _field(provenance, "commits") == "12"
    # High churn is reported, not refused.
    assert float(_field(provenance, "churn_ratio") or "0") > 5


def test_a_rename_only_diff_reports_no_ratio_rather_than_dividing_by_zero(tmp_path: Path) -> None:
    """A pure rename touches no lines; the division is guarded, not attempted."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "mv", "f.txt", "renamed.txt")
    _git(repo, "commit", "-qm", "rename only")
    _fake_codex(tmp_path / "bin", tmp_path / "prompt.txt")

    result = _run(repo, tmp_path, check=False)

    assert result.returncode == 0, result.stderr
    assert _field(_provenance(repo), "churn_ratio") == "n/a"
