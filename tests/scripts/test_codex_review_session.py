"""Tests for the persistent-session mechanism in scripts/codex-review.sh (ADR-0025).

These pin the pieces ADR-0025 makes load-bearing: one warm session resumed across
rounds, read-only *proven* from Codex's own session record (fail-closed), a
durable per-loop identity that a moved base does not carry a stale session
across, graceful degradation to a re-injected cold round when a resume is
unavailable, and the disposition ledger the re-injection reads.

Driven with the shared fake ``codex`` (``_fake_codex``): it reports a thread id,
resumes a recorded one, and writes the session rollout the read-only proof reads,
so no OpenAI call happens.
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


def _git(repo: Path, *args: str) -> str:
    assert _GIT is not None
    return subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [_GIT, *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
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


def _commit(repo: Path, content: str, message: str) -> None:
    (repo / "f.txt").write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


def _provenance(repo: Path, sha: str) -> str:
    return (repo / ".review" / f"{sha}-adversarial.md").read_text().splitlines()[0]


def _field(provenance: str, name: str) -> str | None:
    match = re.search(rf"\b{name}=(\S+?)(?=\s|-->)", provenance)
    return match.group(1) if match else None


def test_round_one_starts_a_session_and_records_its_thread(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    run_review(repo, tmp_path, FAKE_CODEX_THREAD_ID="thread-one")

    prov = _provenance(repo, _git(repo, "rev-parse", "HEAD"))
    assert _field(prov, "thread_id") == "thread-one"
    assert _field(prov, "loop_id"), "a durable loop id is recorded"
    # The thread is persisted for the next round to resume.
    threads = list((repo / ".review" / "session").glob("*.adversarial.thread"))
    assert len(threads) == 1
    assert threads[0].read_text().strip() == "thread-one"


def test_a_later_round_resumes_the_same_thread(tmp_path: Path) -> None:
    """The warm session is resumed, not started cold — the thread id is unchanged."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    run_review(repo, tmp_path, FAKE_CODEX_THREAD_ID="thread-one")

    _commit(repo, "three\n", "round 2")
    result = run_review(repo, tmp_path)

    assert "Resuming Codex" in result.stderr
    prov = _provenance(repo, _git(repo, "rev-parse", "HEAD"))
    # On a resume the recorded thread is carried forward — the fake would only
    # mint a fresh id on a cold start.
    assert _field(prov, "thread_id") == "thread-one"


def test_a_non_read_only_round_fails_closed_and_records_nothing(tmp_path: Path) -> None:
    """Read-only proven, not assumed: a round Codex ran wider is refused (ADR-0025 §4)."""
    repo = tmp_path / "repo"
    _init_repo(repo)

    result = run_review(repo, tmp_path, check=False, FAKE_CODEX_FORCE_SANDBOX="danger-full-access")

    assert result.returncode != 0
    assert "could not prove the review ran read-only" in result.stderr
    assert not (repo / ".review" / f"{_git(repo, 'rev-parse', 'HEAD')}-adversarial.md").exists()


def test_an_unprovable_sandbox_also_fails_closed(tmp_path: Path) -> None:
    """No rollout to read is 'unproven', which is not 'read-only' — it fails closed too."""
    repo = tmp_path / "repo"
    _init_repo(repo)

    # No rollout written, so the effective sandbox cannot be read at all.
    result = run_review(repo, tmp_path, check=False, FAKE_CODEX_NO_ROLLOUT="1")

    assert result.returncode != 0
    assert "could not prove the review ran read-only" in result.stderr


def test_a_failed_resume_degrades_to_a_fresh_session_with_dispositions(tmp_path: Path) -> None:
    """Resume unavailable → cold round with prior findings re-injected (mechanism b)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    run_review(
        repo, tmp_path, FAKE_CODEX_THREAD_ID="thread-one", FAKE_CODEX_REVIEW="finding A\nBLOCK\n"
    )

    _commit(repo, "three\n", "round 2")
    result = run_review(
        repo,
        tmp_path,
        FAKE_CODEX_RESUME_FAIL="1",
        FAKE_CODEX_THREAD_ID="thread-two",
        FAKE_CODEX_PROMPT_COPY=str(tmp_path / "prompt.txt"),
    )

    assert "resume unavailable" in result.stderr
    # A fresh thread was started and recorded, replacing the pruned one.
    prov = _provenance(repo, _git(repo, "rev-parse", "HEAD"))
    assert _field(prov, "thread_id") == "thread-two"
    # The prior round's finding was re-injected into the cold prompt.
    prompt = (tmp_path / "prompt.txt").read_text()
    assert "Prior findings of THIS review" in prompt
    assert "finding A" in prompt


def test_a_moved_base_does_not_carry_a_stale_session(tmp_path: Path) -> None:
    """Re-validation on base move: a rebased branch starts a fresh session (ADR-0025 §1)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    run_review(repo, tmp_path, FAKE_CODEX_THREAD_ID="thread-one")

    # Advance main on a different file (so the rebase is conflict-free) and rebase
    # feature onto it, so the merge base — and thus the loop identity — changes.
    _git(repo, "checkout", "-q", "main")
    (repo / "g.txt").write_text("main moved\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "advance main")
    _git(repo, "checkout", "-q", "feature")
    _git(repo, "rebase", "-q", "main")

    result = run_review(repo, tmp_path, FAKE_CODEX_THREAD_ID="thread-two")

    # A fresh start, not a resume of thread-one — the base moved, so the loop
    # identity changed and the old session is not inherited.
    assert "Resuming Codex" not in result.stderr
    prov = _provenance(repo, _git(repo, "rev-parse", "HEAD"))
    assert _field(prov, "thread_id") == "thread-two"


def test_a_reused_branch_name_does_not_inherit_the_old_loop(tmp_path: Path) -> None:
    """Same branch name + same base reused for unrelated work resets the loop.

    The loop_key collides exactly, so continuation is decided by ancestry: the old
    loop's last reviewed state is not an ancestor of the new branch's HEAD, so its
    session and dispositions are not inherited (ADR-0025 §1's reset on reuse).
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    run_review(
        repo, tmp_path, FAKE_CODEX_THREAD_ID="thread-one", FAKE_CODEX_REVIEW="OLD finding\nBLOCK\n"
    )

    # Delete feature and recreate it off the same base with unrelated work.
    _git(repo, "checkout", "-q", "main")
    _git(repo, "branch", "-qD", "feature")
    _git(repo, "checkout", "-qb", "feature")
    (repo / "h.txt").write_text("unrelated\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "unrelated work")

    result = run_review(
        repo,
        tmp_path,
        FAKE_CODEX_THREAD_ID="thread-two",
        FAKE_CODEX_PROMPT_COPY=str(tmp_path / "prompt.txt"),
    )

    assert "Resuming Codex" not in result.stderr, "the reused name must not resume the old thread"
    prov = _provenance(repo, _git(repo, "rev-parse", "HEAD"))
    assert _field(prov, "thread_id") == "thread-two"
    # The old loop's findings are not re-injected into the fresh loop's prompt.
    assert "OLD finding" not in (tmp_path / "prompt.txt").read_text()


def test_the_bypass_path_keeps_no_session(tmp_path: Path) -> None:
    """The CI bypass is a cold one-shot: no thread, no read-only proof (ADR-0025 §1)."""
    repo = tmp_path / "repo"
    _init_repo(repo)

    run_review(repo, tmp_path, GITHUB_ACTIONS="true")

    prov = _provenance(repo, _git(repo, "rev-parse", "HEAD"))
    assert _field(prov, "thread_id") is None, "bypass records no thread"
    assert not (repo / ".review" / "session").exists()


def test_each_round_writes_a_per_finding_snapshot_with_retirement(tmp_path: Path) -> None:
    """The disposition record is a per-tree snapshot; a dropped finding is retired."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    run_review(repo, tmp_path, FAKE_CODEX_REVIEW="1. **blocker** the value is wrong\nBLOCK\n")
    tree1 = _git(repo, "rev-parse", "HEAD^{tree}")
    _commit(repo, "three\n", "round 2")
    # Round 2 does not re-raise the blocker (author fixed it): it retires.
    run_review(repo, tmp_path, FAKE_CODEX_REVIEW="1. **minor** a small nit\nAPPROVE WITH NITS\n")
    tree2 = _git(repo, "rev-parse", "HEAD^{tree}")

    disp = repo / ".review" / "dispositions"
    # One snapshot per reviewed state, named by the anchor <loop>-<persona>-<tree>.
    assert list(disp.glob(f"*-adversarial-{tree1}.md"))
    snap2 = next(iter(disp.glob(f"*-adversarial-{tree2}.md"))).read_text()
    # The round-2 snapshot carries the new open finding and the retired blocker.
    assert "status=open" in snap2
    assert "severity=minor status=open" in snap2
    assert "severity=blocker status=retired" in snap2
    assert "the value is wrong" in snap2  # retired finding's text is carried forward


def test_two_findings_sharing_a_long_prefix_get_distinct_ids(tmp_path: Path) -> None:
    """The whole finding is hashed, not a prefix, so a shared preamble does not

    collapse two distinct findings into one and silently drop the second.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    prefix = "the reproduction is " + ("x " * 200)
    review = f"1. **major** {prefix} case A fails\n2. **major** {prefix} case B fails\nBLOCK\n"
    run_review(repo, tmp_path, FAKE_CODEX_REVIEW=review)

    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    snap = next(iter((repo / ".review" / "dispositions").glob(f"*-adversarial-{tree}.md")))
    text = snap.read_text()
    # Both distinct findings are recorded, with different ids.
    assert text.count("<!-- finding id=") == 2
    assert "case A fails" in text
    assert "case B fails" in text


def test_a_finding_quoting_the_frame_marker_is_not_truncated(tmp_path: Path) -> None:
    """A review OF this script quotes `<!-- /finding -->`; the record must survive.

    The framing markers in the finding text are escaped, so a quoted terminator
    does not end the block early and drop the grounding that follows it.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    review = "1. **major** the code emits <!-- /finding --> then GROUNDING_TAIL here\nBLOCK\n"
    run_review(repo, tmp_path, FAKE_CODEX_REVIEW=review)

    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    snap = next(iter((repo / ".review" / "dispositions").glob(f"*-adversarial-{tree}.md")))
    text = snap.read_text()
    # Exactly one finding, whole body preserved past the quoted marker.
    assert text.count("<!-- finding id=") == 1
    assert "GROUNDING_TAIL" in text
    # The quoted marker was neutralised, not left as a literal terminator.
    assert "&lt;!-- /finding --&gt;" in text


def test_nested_numbered_steps_do_not_split_a_finding(tmp_path: Path) -> None:
    """Indented reproduction steps stay part of their finding, not new findings."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    review = (
        "1. **major** it fails, reproduce with:\n"
        "    1. start the service\n"
        "    2. send a request\n"
        "   and it crashes.\n"
        "BLOCK\n"
    )
    run_review(repo, tmp_path, FAKE_CODEX_REVIEW=review)

    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    snap = next(iter((repo / ".review" / "dispositions").glob(f"*-adversarial-{tree}.md")))
    text = snap.read_text()
    # Exactly one finding — the nested "1." / "2." steps did not spawn more.
    assert text.count("<!-- finding id=") == 1
    assert "send a request" in text
