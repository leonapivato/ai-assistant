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
import time
from hashlib import sha1
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _fake_codex import SCRIPT, artifact_for, bash, run_review
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
    # Nor is the log offered as conclusive: growth is positive evidence, a static
    # log says nothing either way, and the claim is what ends the window
    # (adversarial round 4 on PR #1722; the gap itself is issue #1730).
    assert "Nothing here is conclusive" in started.stderr
    assert "says nothing either way" in started.stderr
    # And "ask again" is not an instruction to poll forever: a child that has
    # gone will never claim, so the exit from the window is named, with the check
    # that confirms it (adversarial round 5 on PR #1722).
    # Scoped to THIS clone by the script's own absolute path: a sibling clone
    # running the same persona must not read as this round still being alive
    # (adversarial round 6 on PR #1722). Matched as a FIXED STRING, because a
    # path is not a pattern (adversarial round 7; pinned end-to-end by
    # ``test_the_liveness_check_reads_a_clone_path_as_data_not_as_syntax``).
    assert _confirm_command(started.stderr) == (
        "ps -eo pid,args | "
        f"""grep -F -f <(printf '%s\\n' '{SCRIPT} adversarial ') | """
        'grep -v "^ *$$ "   # this clone\'s round only'
    )
    assert "pgrep" not in started.stderr
    assert "relaunching IS" in started.stderr
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


def _confirm_command(stderr: str) -> str:
    """The one command the grace-expiry message offers as a liveness check.

    Located by its own first words rather than by line number, so a reworded
    paragraph around it does not quietly turn this into an assertion about
    nothing.
    """
    lines = [line.strip() for line in stderr.splitlines() if line.strip().startswith("ps ")]
    assert len(lines) == 1, lines
    return lines[0]


def _single_quoted(text: str) -> str:
    """POSIX single-quoting, in the ``'\\''`` spelling the script emits.

    Not ``shlex.quote``: that spells an embedded quote ``'"'"'``, which is
    equally valid and a different string, and this is an assertion about the
    exact bytes a reader sees.
    """
    return "'" + text.replace("'", "'\\''") + "'"


def _shell(command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run exactly what the message printed, the way an operator would paste it."""
    return subprocess.run(  # noqa: S603  # resolved bash, running this repo's own message
        [bash(), "-c", command], cwd=cwd, check=False, capture_output=True, text=True
    )


@pytest.mark.skipif(shutil.which("flock") is None, reason="the loop lock needs flock")
@pytest.mark.skipif(shutil.which("ps") is None, reason="the liveness check needs ps")
def test_the_liveness_check_reads_a_clone_path_as_data_not_as_syntax(
    tmp_path: Path,
) -> None:
    """A clone path is data. Two layers used to read it as syntax; neither may.

    The grace-expiry message names the one case in ``--start``'s mode where a
    second round is the right move: the child has *gone*, so no claim will ever
    arrive. It has the operator confirm that with a process listing, and that
    listing is both a **pattern** for the matcher and **shell source** for the
    reader who pastes it. Interpolating a path into either is the same bug twice.

    *As a pattern* (adversarial round 7). It used to print
    ``pgrep -fa "<script> <persona> "``, and ``pgrep -f`` reads its argument as an
    ERE: under a clone at ``…/clone+[1]/…`` the ``+`` repeats an ``e``, ``[1]`` is
    a character class, an unbalanced bracket is invalid outright — and the live
    child does not match. The message then walks a lane into relaunching a round
    that is still running, which is the paid-round-thrown-away failure the whole
    mode exists to prevent.

    *As shell source* (adversarial round 8). The needle was interpolated into a
    double-quoted string, so a clone at ``…/$(touch pwned)/…`` ran the
    substitution on paste, and a ``"`` or a backtick broke the quoting outright.

    So the clone here carries both kinds at once, and the printed command is run
    for real: against a round alive at that moment — held short of its claim by
    the review-loop lock, exactly as the slow case is — and again once that round
    has finished.

    That second run is the reason the needle goes through ``-f`` and the caller's
    own pid is dropped. ``pgrep`` excluded its own process from the listing;
    ``grep`` does not, and neither ever excluded the shell running the pasted
    line. Either self-match makes the command always print something, and "no
    match" is the entire signal here, so it has to be reachable.
    """
    # Every character here is one of the two layers' metacharacters: `+[]` for
    # the ERE, `$(…)`, a backtick, `'` and `"` for the shell. The `$(touch
    # pwned)` is live: if the needle ever reaches a reader's shell unquoted, the
    # file appears.
    hostile = "clone+[1]$(touch pwned)`it's\"q"
    clone = tmp_path / hostile / "scripts"
    clone.mkdir(parents=True)
    script = clone / "codex-review.sh"
    shutil.copy(SCRIPT, script)

    repo = tmp_path / "repo"
    _init_repo(repo)
    env = _env(tmp_path, CODEX_REVIEW_START_GRACE="1")
    flock = shutil.which("flock")
    assert flock is not None
    holder = subprocess.Popen(  # noqa: S603  # resolved flock, test-controlled path
        [flock, str(_loop_lock(repo)), "sleep", "20"]
    )
    try:
        started = subprocess.run(  # noqa: S603  # resolved bash, test-controlled copy
            [bash(), str(script), "--start", "adversarial", "main"],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert started.returncode == 1
        command = _confirm_command(started.stderr)

        # Single-quoted, with the one character single quotes cannot carry closed
        # and reopened — so the path is still legible to a reader checking it
        # against their own clone, and inert to the shell that reads the line.
        assert _single_quoted(f"{script} adversarial ") in command

        # And it finds the round that is alive right now, blocked on the loop
        # lock. This is the assertion the `pgrep -f` form failed.
        assert f"{script} adversarial" in _shell(command, tmp_path).stdout
        assert not (tmp_path / "pwned").exists()
    finally:
        holder.terminate()
        holder.wait()

    # Once the round is genuinely gone the same command says so, by printing
    # nothing at all — which is the half that makes "no match" mean something.
    #
    # The round's departure is awaited through the listing itself rather than
    # through `--wait`, deliberately: in the window this whole message is about,
    # `--wait` can answer exit 4 about a live round (issue #1730), so an assertion
    # on it here would be an assertion about that gap under load and not about
    # this command. That the child ran at all is already established above.
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline and _shell(command, tmp_path).stdout != "":
        time.sleep(0.2)
    assert _shell(command, tmp_path).stdout == ""
    assert not (tmp_path / "pwned").exists()
