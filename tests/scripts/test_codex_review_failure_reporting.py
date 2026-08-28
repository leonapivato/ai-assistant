"""A round that fails says why, detached as much as in the foreground.

Issues #1674 and #1675 each record the same shape, twice: a detached round whose
log ends at ``Running Codex '<persona>' review of HEAD vs '…'`` with no error
line at all, no traceback and no partial output. Both lanes spent time
diagnosing a ``codex`` that was healthy, and #1674 explicitly checked that a bare
``codex exec`` with the same flags returned normally.

The mechanism is in the driver, not in Codex. Under ``--json`` the CLI puts its
whole event stream — the ``error`` and ``turn.failed`` events included — on
**stdout**, and leaves stderr empty; ``codex-review.sh`` redirects that stdout
into a ``mktemp`` file the ``EXIT`` trap deletes, and the fresh-session call was a
bare command under ``set -e``, which exits without a word of its own. The reason
was written down and then thrown away.

So these tests drive a ``codex`` that fails exactly the way the real one does —
non-zero, everything on stdout, **nothing on stderr** — and require that the
reason reaches the operator: on the terminal in the foreground, and in the
detached log ``--wait`` prints as its evidence for exit 4.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from hashlib import sha1
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _fake_codex import artifact_for, run_review
from test_codex_review_start_wait import NOT_IN_FLIGHT, _env, _fields, _git, _init_repo, _run

if TYPE_CHECKING:
    from subprocess import CompletedProcess


def _refused_round(tmp_path: Path) -> tuple[Path, CompletedProcess[str]]:
    """A round whose fresh session the service refuses, run in the foreground."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    result = run_review(
        repo, tmp_path, "adversarial", "main", check=False, FAKE_CODEX_START_FAIL="1"
    )
    return repo, result


def test_a_refused_fresh_session_names_its_status_and_quotes_the_stream(
    tmp_path: Path,
) -> None:
    _repo, result = _refused_round(tmp_path)

    assert result.returncode != 0
    assert "codex exec (the fresh read-only session) exited 1" in result.stderr
    assert "the service refused this request" in result.stderr


def test_the_reason_is_recovered_from_stdout_where_codex_puts_it(tmp_path: Path) -> None:
    """The fake writes nothing to stderr, exactly as codex-cli 0.146.0 does not.

    If the driver ever went back to letting ``set -e`` end the round, this is the
    assertion that fails: there is no other source for the sentence.
    """
    _repo, result = _refused_round(tmp_path)

    assert "turn.failed" in result.stderr


def test_a_refused_round_still_records_no_artifact(tmp_path: Path) -> None:
    """Reporting the failure is all that changed; the round still fails closed."""
    repo, result = _refused_round(tmp_path)

    assert result.returncode != 0
    assert artifact_for(repo, _git(repo, "rev-parse", "HEAD")) is None


def test_a_failed_resume_says_why_before_it_degrades(tmp_path: Path) -> None:
    """The fresh start truncates the stream, so this is the only moment it exists.

    A pruned session and a refused request degrade identically into the fresh
    start, and telling them apart is the difference between "the ADR-0025 §1
    fallback worked" and "the service is refusing this loop".
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    first = run_review(repo, tmp_path, "adversarial", "main")
    assert first.returncode == 0, first.stderr
    (repo / "f.txt").write_text("three\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "another change")

    result = run_review(repo, tmp_path, "adversarial", "main", FAKE_CODEX_RESUME_FAIL="1")

    assert result.returncode == 0, result.stderr
    assert "resume unavailable" in result.stderr
    assert "codex exec (resume " in result.stderr


def test_a_detached_round_that_dies_leaves_the_reason_in_its_log(tmp_path: Path) -> None:
    """The whole point: #1674's and #1675's log ended at "Running Codex …".

    ``--wait`` already prints that log as its evidence for exit 4; what was
    missing was anything in it to read.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    env = _env(tmp_path, FAKE_CODEX_START_FAIL="1")

    started = _run(repo, env, "--start", "adversarial", "main")
    assert started.returncode == 0, started.stderr
    log = repo / _fields(started.stdout)["log"]
    waited = _run(repo, env, "--wait", "adversarial", "main", "--timeout", "30")

    assert waited.returncode == NOT_IN_FLIGHT, waited.stderr
    assert "recorded no artifact" in waited.stderr
    assert "the service refused this request" in log.read_text()
    assert "the service refused this request" in waited.stderr


def test_a_turn_that_fails_while_the_process_exits_zero_is_quoted(tmp_path: Path) -> None:
    """The other half: ``--json`` can carry a failure and still exit 0.

    Nothing is written to ``-o`` then, so the empty-review guard is what catches
    it — and the reason is in the event stream, on the stdout this script routes
    into a temp file it is about to delete. Asserting on the failure's own
    message rather than on the stream merely being non-empty: an implementation
    that quoted only completed streams would satisfy the weaker form.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)

    result = run_review(
        repo, tmp_path, "adversarial", "main", check=False, FAKE_CODEX_TURN_FAILED="1"
    )

    assert result.returncode != 0
    assert "codex produced an empty review" in result.stderr
    assert "the turn failed mid-stream" in result.stderr


def _loop_lock(repo: Path, base: str = "main") -> Path:
    """The review-loop lock file for this repo's current branch and base.

    Computed the way the script computes it — ``sha1(branch)-sha1(base_sha)`` —
    because a test that guessed the path would silently stop holding anything the
    day the key changed, and the assertion it supports would still pass.
    """
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    base_sha = _git(repo, "merge-base", base, "HEAD")
    key = f"{sha1(branch.encode()).hexdigest()}-{sha1(base_sha.encode()).hexdigest()}"  # noqa: S324
    session = repo / ".review" / "session"
    session.mkdir(parents=True, exist_ok=True)
    return session / f"{key}.lock"


@pytest.mark.skipif(shutil.which("flock") is None, reason="the loop lock needs flock")
def test_an_unconfirmed_start_leads_with_the_action_not_with_a_failure(
    tmp_path: Path,
) -> None:
    """Issue #1670: the message read as "it failed at startup", and it never was.

    Twice reported, and on every reported occasion the round was running and went
    on to record its artifact. A lane that believes the round is dead is one step
    from starting a second one, which is the paid-round-thrown-away failure
    ``--start`` exists to prevent.

    The round is held short of its claim by holding the review-loop lock, which a
    round takes on the way to publishing the marker ``--start`` polls for. That is
    the real shape of the slow case: alive, healthy, and not yet claimed.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    env = _env(tmp_path, CODEX_REVIEW_START_GRACE="1")
    flock = shutil.which("flock")
    assert flock is not None
    holder = subprocess.Popen(  # noqa: S603  # resolved flock, test-controlled path
        [flock, str(_loop_lock(repo)), "sleep", "20"]
    )
    try:
        started = _run(repo, env, "--start", "adversarial", "main")
    finally:
        holder.terminate()
        holder.wait()

    assert started.returncode == 1
    assert "failed at startup" not in started.stderr
    assert "was not started with --start" not in started.stderr
    assert "Nothing here has killed it" in started.stderr
    assert "--wait adversarial" in started.stderr
    # And it does not promise what `--wait` cannot deliver here. An unclaimed
    # child has published neither the marker nor the lock `--wait` reads, so
    # `--wait` answers exit 4 about a round that is alive — the one window where
    # a 4 is not "stop polling". A message that sent a lane there calling `--wait`
    # conclusive would be walking it into the relaunch this mode exists to stop
    # (adversarial round 3 on PR #1722).
    assert "the only thing" not in started.stderr
    assert "NOT the 'stop polling'" in started.stderr
    # The round it could not confirm is still a real round, and finishes.
    assert _run(repo, env, "--wait", "adversarial", "main", "--timeout", "60").returncode == 0


def test_a_foreground_round_is_not_described_as_a_detached_one(tmp_path: Path) -> None:
    """``--wait`` reads the log path the round itself recorded, or says there is none.

    A round run in the foreground records an empty ``log=`` in its marker, because
    its output went to the terminal. The replaced fallback said that as "this
    round was not started with --start" *whenever the file was empty*, which is
    the sentence issue #1674 read — correctly — as a claim about the wrong round.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    failed = run_review(
        repo, tmp_path, "adversarial", "main", check=False, FAKE_CODEX_START_FAIL="1"
    )
    assert failed.returncode != 0

    waited = _run(repo, _env(tmp_path), "--wait", "adversarial", "main", "--timeout", "5")

    assert waited.returncode == NOT_IN_FLIGHT
    assert "went to the terminal that ran it" in waited.stderr
