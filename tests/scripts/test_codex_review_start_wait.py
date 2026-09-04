"""Tests for the ``--start``/``--wait`` modes of scripts/codex-review.sh (issue #1594).

A round runs for minutes, and a caller that cannot hold one process open that long
has to start it and poll it instead. What these pin is the part that decides
whether such a caller behaves: the three answers ``--wait`` gives, the exit status
carrying each — 0 recorded, 3 ``still running``, 4 no round in flight for HEAD's
tree — and the **tree match** that decides which of them is right. A wait that
reported a round running on some other tree would hand the caller a review of
content it has already changed, which is the failure the tree match exists for, so
it is exercised by breaking it: a commit lands under a round in flight.

The property underneath all of it is that ``--start`` launches the driver's own
foreground round rather than reimplementing one, so the artifact ``--wait`` reports
is the artifact the round recorded — asserted directly rather than assumed.

Driven with the shared fake ``codex`` (``_fake_codex``), so no OpenAI call happens.
``FAKE_CODEX_PRE_CMD`` is what makes a round slow enough to observe in flight.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _fake_codex import (  # path-inserted shared test helper
    SCRIPT,
    artifact_for,
    bash,
    install_fake_codex,
    require_artifact,
    review_env,
    run_review,
)
from _repo_template import seed_repo

_GIT = shutil.which("git")

# The three answers, named. A caller's next move differs for each, and confusing
# two of them is precisely what the modes exist to stop (see the module docstring).
RECORDED = 0
STILL_RUNNING = 3
NOT_IN_FLIGHT = 4
USAGE = 2


def _git(repo: Path, *args: str) -> str:
    assert _GIT is not None
    return subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [_GIT, *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir()
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


def _commit(repo: Path, content: str, message: str) -> None:
    (repo / "f.txt").write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


def _tree(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD^{tree}")


def _env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    """The fake on PATH, an isolated CODEX_HOME, and a one-second poll."""
    install_fake_codex(tmp_path / "bin")
    return review_env(tmp_path, CODEX_REVIEW_WAIT_INTERVAL="1", **overrides)


def _run(repo: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # resolved bash, in-repo script, test env
        [bash(), str(SCRIPT), *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _fields(stdout: str) -> dict[str, str]:
    """The ``key=value`` lines a mode writes to stdout, as a mapping."""
    out = {}
    for line in stdout.splitlines():
        key, _, value = line.partition("=")
        out[key] = value
    return out


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _round_pids(repo: Path) -> list[int]:
    pids = []
    for marker in (repo / ".review" / "session").glob("*.round"):
        for line in marker.read_text().splitlines():
            if line.startswith("pid="):
                with contextlib.suppress(ValueError):
                    pids.append(int(line.removeprefix("pid=")))
    return pids


def _reap(repo: Path, seconds: float = 60.0) -> None:
    """Block until no round this repo started is still running.

    A detached round outlives the ``--start`` that launched it — that is the whole
    point of it — so a test that leaves one in flight would leave a process writing
    into a ``tmp_path`` pytest is about to remove. Every test that starts a round it
    does not wait out reaps it here.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not any(_alive(pid) for pid in _round_pids(repo)):
            return
        time.sleep(0.2)


def _await_round(repo: Path, seconds: float = 30.0) -> None:
    """Block until a round has published the tree it pinned.

    `--start` does this for its caller and does not return until it has. A round
    launched some other way — the foreground one below — has no such handshake, so a
    test that polls it must wait for the round to establish itself first, or it is
    racing a process that has not reached its first statement.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for marker in (repo / ".review" / "session").glob("*.round"):
            if f"tree={_tree(repo)}" in marker.read_text():
                return
        time.sleep(0.2)
    raise AssertionError("no round published a tree within the deadline")


def _hold_round_until(gate: Path) -> str:
    """A ``FAKE_CODEX_PRE_CMD`` that parks the round until ``gate`` exists.

    The round is what publishes the artifact, so gating it is what lets a test
    state *when* publication happens instead of racing a `sleep` against it. It
    gives up after a minute rather than parking forever, so a test that fails
    before it opens the gate leaves nothing behind.

    It is how every test here that needs a round *in flight* keeps one, rather
    than by sleeping for longer than the assertions take. A ``sleep`` is wrong in
    both directions: too short and the round finishes mid-assertion under load,
    too long and everything waiting for the round to end -- ``_reap``, a
    ``--wait`` for the artifact -- waits out the remainder of a sleep nothing
    needs. That cost the module about 50 s of its 75 s (issue #1752).
    """
    return f'for _ in $(seq 600); do [ -e "{gate}" ] && break; sleep 0.1; done'


def test_start_returns_while_the_round_runs_and_wait_reports_its_artifact(tmp_path: Path) -> None:
    """The split's whole point, end to end — and the artifact is the round's own."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    release = tmp_path / "let-the-round-finish"
    env = _env(tmp_path, FAKE_CODEX_PRE_CMD=_hold_round_until(release))

    started = _run(repo, env, "--start", "adversarial", "main")

    assert started.returncode == 0, started.stderr
    fields = _fields(started.stdout)
    assert fields["tree"] == _tree(repo)
    assert fields["sha"] == _git(repo, "rev-parse", "HEAD")
    assert fields["loop_id"] not in ("", "noloop")
    # It really did return before the round finished: the round is still parked,
    # by construction rather than by outrunning a sleep.
    assert artifact_for(repo, _git(repo, "rev-parse", "HEAD")) is None

    release.touch()
    waited = _run(repo, env, "--wait", "adversarial", "main", "--timeout", "60")

    assert waited.returncode == RECORDED, waited.stderr
    reported = _fields(waited.stdout)
    assert reported["verdict"] == "APPROVE"
    assert reported["tree"] == _tree(repo)
    assert reported["round"] == "1"
    # Not "an" artifact — the one the round recorded. `--start` re-executes the
    # driver's foreground form, so there is no second thing that could be reported.
    assert repo / reported["artifact"] == require_artifact(repo, _git(repo, "rev-parse", "HEAD"))


def test_a_wait_that_times_out_says_still_running_and_loses_nothing(tmp_path: Path) -> None:
    """Exit 3 is 'ask again'. The round survives the deadline that reported it."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    release = tmp_path / "let-the-round-finish"
    env = _env(tmp_path, FAKE_CODEX_PRE_CMD=_hold_round_until(release))
    _run(repo, env, "--start", "adversarial", "main")

    early = _run(repo, env, "--wait", "adversarial", "main", "--timeout", "1")

    assert early.returncode == STILL_RUNNING
    assert "still running" in early.stderr
    assert early.stdout == ""

    release.touch()
    later = _run(repo, env, "--wait", "adversarial", "main", "--timeout", "60")

    assert later.returncode == RECORDED, later.stderr
    assert _fields(later.stdout)["verdict"] == "APPROVE"


def test_wait_refuses_a_round_that_is_reviewing_a_different_tree(tmp_path: Path) -> None:
    """Break the tree match: commit under a round in flight.

    A round is in flight and its lock is held, so a wait that matched on the lock
    alone would keep waiting and then report a review of the tree the author has
    just moved off. `--wait` is asked about HEAD's tree, so it names both trees and
    exits 4 — no round is in flight *for that tree*, which is the truth.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    release = tmp_path / "let-the-round-finish"
    env = _env(tmp_path, FAKE_CODEX_PRE_CMD=_hold_round_until(release))
    _run(repo, env, "--start", "adversarial", "main")
    reviewed_tree = _tree(repo)

    _commit(repo, "three\n", "a commit landing under the round")
    moved = _run(repo, env, "--wait", "adversarial", "main", "--timeout", "60")

    assert moved.returncode == NOT_IN_FLIGHT
    assert reviewed_tree[:12] in moved.stderr
    assert _tree(repo)[:12] in moved.stderr
    assert moved.stdout == ""
    # And the round in flight records nothing for either tree: the driver's own
    # settled-tree check refuses it, which is what makes exit 4 the honest answer.
    release.touch()
    _reap(repo)
    assert artifact_for(repo, _git(repo, "rev-parse", "HEAD")) is None


def test_wait_says_no_round_is_in_flight_when_none_was_started(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    result = _run(repo, _env(tmp_path), "--wait", "adversarial", "main", "--timeout", "0")

    assert result.returncode == NOT_IN_FLIGHT
    assert "no 'adversarial' round is in flight" in result.stderr
    assert "--start adversarial" in result.stderr


def test_wait_reports_a_round_that_died_without_recording(tmp_path: Path) -> None:
    """The third shape of exit 4, and the one a caller cannot diagnose alone.

    The round claimed the loop and then failed a validation, so there is a marker
    for HEAD's tree, no lock, and no artifact. Polling forever is the wrong move and
    so is starting a second round blindly; `--wait` says which it is and shows the
    detached round's own output.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    env = _env(tmp_path, FAKE_CODEX_REVIEW="", FAKE_CODEX_PRE_CMD="sleep 1")
    assert _run(repo, env, "--start", "adversarial", "main").returncode == 0

    result = _run(repo, env, "--wait", "adversarial", "main", "--timeout", "60")

    assert result.returncode == NOT_IN_FLIGHT
    assert "is no longer" in result.stderr
    assert "recorded no artifact" in result.stderr
    assert "codex produced an empty review" in result.stderr


def _attach_to_blocking_artifact(path: Path, seconds: float = 60.0) -> int:
    """Block until something is reading the named pipe at ``path``; hold a writer.

    Non-blocking, so the open fails with ``ENXIO`` until a reader is there rather
    than hanging the suite when nothing ever reads it — which makes its success a
    *proof* that the reader has arrived, and that is what the test below needs
    before it may let anything else happen.

    The returned descriptor is deliberately left open and empty: a writer exists,
    so the reader stays blocked with nothing to read, and the caller decides when
    it is released by writing into it. Closing it here instead would send the
    reader an immediate EOF, which is the opposite of a hold.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            return os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        except OSError:
            time.sleep(0.05)
    raise AssertionError(f"nothing read {path} within {seconds}s")


def test_wait_reports_a_round_that_finished_while_the_poll_was_looking(tmp_path: Path) -> None:
    """Issues #1629 and #1630: 'the round is gone' must never be read first.

    A round renames its artifact into place and only *then* exits, so the two
    observations are ordered on disk — and `--wait` has to read them in that same
    order, liveness before the artifact directory. Reading the directory first
    inverts it: a round that records and exits between the two reads is seen as
    neither, and exit 4 — "stop polling, nothing is coming" — is reported about a
    finished, green, already-paid round. Three lanes were told that in one day, and
    `worker.md` tells a lane a 4 is never a reason to wait again, so the natural
    next move is to relaunch the round that just succeeded.

    The interleaving is forced in BOTH directions rather than raced for, because a
    test that only raced would fail in the silent direction: if the poll were
    scheduled late, its listing would be expanded after publication, the inverted
    order would answer 0 as well, and the test would pass while covering nothing.
    So a named pipe in the artifact directory blocks the `head` that reads each
    candidate's provenance, and the round itself is parked until this test opens
    its gate. The four steps below then establish, in order and by construction:
    the poll is inside a listing (the pipe has a reader), that listing predates
    publication (the round is still parked), the round has published and exited
    (the gate is open and it is reaped), and only then is the listing released.

    Under the inverted order that stale listing is the one the answer is computed
    from, and the answer is exit 4 about a green round. Under this one the listing
    is taken after the liveness observation it must outlive, so the round is seen
    running, and the artifact is found on the next poll.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    gate = tmp_path / "let-the-round-publish"
    env = _env(tmp_path, FAKE_CODEX_PRE_CMD=_hold_round_until(gate))
    assert _run(repo, env, "--start", "adversarial", "main").returncode == 0

    # Created only now: the round's own round-count scan reads this directory
    # before it publishes the marker `--start` returns on, so nothing of the round
    # can block on this pipe.
    blocker = repo / ".review" / "0-blocking-not-an-artifact.md"
    os.mkfifo(blocker)
    waiter = subprocess.Popen(  # noqa: S603  # resolved bash, in-repo script
        [bash(), str(SCRIPT), "--wait", "adversarial", "main", "--timeout", "120"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    held = -1
    try:
        # 1. The poll is inside a listing, and 2. that listing was expanded while
        #    the round was still parked, so it cannot contain the artifact.
        held = _attach_to_blocking_artifact(blocker)
        blocker.unlink()
        # 3. Let the round publish and exit. Its artifact is renamed into place
        #    before the process goes, so reaping it establishes both.
        gate.touch()
        _reap(repo)
        # 4. Release the listing from step 1 — the stale one.
        os.write(held, b"not a review artifact\n")
        os.close(held)
        held = -1
        stdout, stderr = waiter.communicate(timeout=120)
    finally:
        if held != -1:
            os.close(held)
        gate.touch()  # never leave a parked round behind, however this exited
        if waiter.poll() is None:
            waiter.kill()
            waiter.communicate()
        _reap(repo)
        with contextlib.suppress(FileNotFoundError):
            blocker.unlink()

    assert waiter.returncode == RECORDED, stderr
    reported = _fields(stdout)
    assert reported["verdict"] == "APPROVE"
    assert reported["tree"] == _tree(repo)
    assert repo / reported["artifact"] == require_artifact(repo, _git(repo, "rev-parse", "HEAD"))


def test_wait_says_still_running_about_a_round_that_has_already_finished(
    tmp_path: Path,
) -> None:
    """Issue #1635: the one direction the liveness-first order can still be wrong in.

    `--wait` reads liveness before the artifact directory (#1629, #1630), and the
    script's own comment states the residue that order leaves and calls it
    harmless:

        a round that finishes after the liveness read is reported as still
        running, and the next poll -- one interval later -- reports its artifact.

    That was prose in a comment and in PR #1633's body, asserted nowhere. It is
    pinned here as behaviour, because "harmless" is a claim about what the caller
    is told next: exit 3 means *call again*, so a caller that obeys it loses
    nothing, whereas the same moment answered 4 -- "stop polling, nothing is
    coming" -- would throw away a green, already-paid round, which is exactly
    #1629's failure.

    Two neighbours are close but neither states this. The `--timeout 1` test above
    reports exit 3 about a round that is genuinely still parked; this one reports
    it about a round that is provably *gone*, with its artifact already on disk.
    And `..._finished_while_the_poll_was_looking` forces the same interleaving but
    with a deadline generous enough to swallow it, so the caller only ever sees
    the 0 -- the intermediate answer is never observed. Here the deadline falls
    inside the window, so the 3 is the answer a real caller gets.

    The interleaving is forced, not raced, by the same two devices that test uses:
    the round is parked until this test opens its gate, and a named pipe in the
    artifact directory blocks the poll *inside* its listing, after the liveness
    observation it must outlive. `--timeout 0` is what turns that iteration into
    the reported answer rather than one poll of many.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    gate = tmp_path / "let-the-round-publish"
    env = _env(tmp_path, FAKE_CODEX_PRE_CMD=_hold_round_until(gate))
    assert _run(repo, env, "--start", "adversarial", "main").returncode == 0

    # After `--start`, for the reason the neighbouring test gives: the round's own
    # round-count scan reads this directory before it publishes its marker.
    blocker = repo / ".review" / "0-blocking-not-an-artifact.md"
    os.mkfifo(blocker)
    waiter = subprocess.Popen(  # noqa: S603  # resolved bash, in-repo script
        [bash(), str(SCRIPT), "--wait", "adversarial", "main", "--timeout", "0"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    held = -1
    try:
        # The poll is inside its listing, so liveness has been read and the round
        # was alive when it was; the listing predates publication, since the round
        # is still parked.
        held = _attach_to_blocking_artifact(blocker)
        blocker.unlink()
        # The round now publishes and exits -- strictly after that liveness read.
        gate.touch()
        _reap(repo)
        assert artifact_for(repo, _git(repo, "rev-parse", "HEAD")) is not None
        pids = _round_pids(repo)
        assert pids != []
        assert not any(_alive(pid) for pid in pids)
        # Release the stale listing; the deadline has long since passed.
        os.write(held, b"not a review artifact\n")
        os.close(held)
        held = -1
        stdout, stderr = waiter.communicate(timeout=120)
    finally:
        if held != -1:
            os.close(held)
        gate.touch()  # never leave a parked round behind, however this exited
        if waiter.poll() is None:
            waiter.kill()
            waiter.communicate()
        _reap(repo)
        with contextlib.suppress(FileNotFoundError):
            blocker.unlink()

    assert waiter.returncode == STILL_RUNNING, stderr
    assert waiter.returncode != NOT_IN_FLIGHT
    assert "still running" in stderr
    assert "call --wait again" in stderr, "exit 3 has to say 'ask again' to be harmless"
    assert stdout == ""
    # Not a 4 wearing a 3's exit status: none of exit 4's three sentences is here.
    assert "recorded no artifact" not in stderr
    assert "no 'adversarial' round is in flight" not in stderr
    assert "is reviewing tree" not in stderr

    # And the very next poll is the 0 the comment promises, needing no new round.
    settled = _run(repo, env, "--wait", "adversarial", "main", "--timeout", "0")

    assert settled.returncode == RECORDED, settled.stderr
    assert settled.returncode != NOT_IN_FLIGHT
    reported = _fields(settled.stdout)
    assert reported["verdict"] == "APPROVE"
    assert reported["tree"] == _tree(repo)
    assert repo / reported["artifact"] == require_artifact(repo, _git(repo, "rev-parse", "HEAD"))


def test_start_refuses_a_second_round_of_the_same_persona(tmp_path: Path) -> None:
    """ADR-0015 and #142's rule, refused at the start rather than in a log."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    release = tmp_path / "let-the-round-finish"
    env = _env(tmp_path, FAKE_CODEX_PRE_CMD=_hold_round_until(release))
    assert _run(repo, env, "--start", "adversarial", "main").returncode == 0

    second = _run(repo, env, "--start", "adversarial", "main")

    assert second.returncode == 1
    assert "already running" in second.stderr
    assert "--wait adversarial" in second.stderr
    release.touch()
    _reap(repo)


def test_wait_attributes_a_round_started_in_the_foreground(tmp_path: Path) -> None:
    """Issue #1594's second recorded case: a foreground call cut off mid-round.

    Nothing about that round is detached, so `--start` never ran and there is no
    log — but a round publishes the tree it pinned whichever way it was launched,
    so the poll still finds it rather than reporting nothing in flight.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    release = tmp_path / "let-the-round-finish"
    env = _env(tmp_path, FAKE_CODEX_PRE_CMD=_hold_round_until(release))
    foreground = subprocess.Popen(  # noqa: S603  # resolved bash, in-repo script
        [bash(), str(SCRIPT), "adversarial", "main"],
        cwd=repo,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # Parked, so the poll below meets a round genuinely in flight; released
        # only once it has, so the wait is not sitting out the rest of a sleep.
        _await_round(repo)
        release.touch()
        waited = _run(repo, env, "--wait", "adversarial", "main", "--timeout", "60")
    finally:
        release.touch()
        foreground.wait(timeout=60)

    assert waited.returncode == RECORDED, waited.stderr
    assert _fields(waited.stdout)["verdict"] == "APPROVE"


def test_wait_reports_an_artifact_that_is_already_recorded(tmp_path: Path) -> None:
    """No round need be in flight: the question is about HEAD's tree, not a process."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    run_review(repo, tmp_path)

    result = _run(repo, _env(tmp_path), "--wait", "adversarial", "main", "--timeout", "0")

    assert result.returncode == RECORDED, result.stderr
    reported = _fields(result.stdout)
    assert reported["round"] == "1"
    assert reported["verdict"] == "APPROVE"


def _path_without_codex() -> str | None:
    """A PATH carrying the tools the script needs but no ``codex``, or ``None``."""
    dirs: list[str] = []
    for tool in ("git", "bash", "sed", "awk", "grep", "head", "tail", "date", "flock"):
        found = shutil.which(tool)
        if found is None:
            continue
        parent = str(Path(found).parent)
        if parent not in dirs:
            dirs.append(parent)
    path = os.pathsep.join(dirs)
    if shutil.which("git", path=path) is None or shutil.which("codex", path=path) is not None:
        return None
    return path


def test_wait_does_not_need_the_codex_cli(tmp_path: Path) -> None:
    """It reads `.review/` and a lock file and calls nothing.

    Requiring the CLI it never invokes would fail the one mode whose job is to
    REPORT on a round — including a round started on a host this one only observes.
    """
    path = _path_without_codex()
    if path is None:
        pytest.skip("no PATH available that carries git but not codex")
    repo = tmp_path / "repo"
    _init_repo(repo)
    env = review_env(tmp_path)
    env["PATH"] = path

    result = _run(repo, env, "--wait", "adversarial", "main", "--timeout", "0")

    assert result.returncode == NOT_IN_FLIGHT
    assert "codex CLI not found" not in result.stderr


def test_wait_warns_on_a_dirty_tree_rather_than_refusing(tmp_path: Path) -> None:
    """Its inputs are HEAD's tree and a lock, neither of which the dirt changes.

    Refusing would withhold the diagnosis in the case it is most wanted — a round
    in flight while the tree has drifted under it. The round *is* refused, as ever.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    run_review(repo, tmp_path)
    (repo / "scratch.txt").write_text("untracked\n")

    waited = _run(repo, _env(tmp_path), "--wait", "adversarial", "main", "--timeout", "0")
    started = _run(repo, _env(tmp_path), "--start", "adversarial", "main")

    assert waited.returncode == RECORDED, waited.stderr
    assert "working tree is dirty" in waited.stderr
    assert started.returncode != 0
    assert "commit or stash first" in started.stderr


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--start", "--wait", "adversarial"], "alternatives"),
        (["--timeout", "60", "adversarial"], "--timeout applies to --wait only"),
        (["--wait", "adversarial", "--timeout", "sixty"], "--timeout must be"),
        (["--wait", "adversarial", "--timeout", "060"], "leading zero"),
        (["--wait", "adversarial", "--timeout"], "needs a value"),
        (["--bogus", "adversarial"], "unknown option"),
        (["--wait", "adversarial", "main", "extra"], "usage:"),
    ],
)
def test_argument_errors_are_refused(tmp_path: Path, args: list[str], message: str) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    result = _run(repo, _env(tmp_path), *args)

    assert result.returncode == USAGE, result.stderr
    assert message in result.stderr


def test_a_malformed_poll_interval_is_refused_before_it_spins(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    env = _env(tmp_path)
    env["CODEX_REVIEW_WAIT_INTERVAL"] = "0"

    result = _run(repo, env, "--wait", "adversarial", "main", "--timeout", "5")

    assert result.returncode == USAGE
    assert "CODEX_REVIEW_WAIT_INTERVAL" in result.stderr


def test_start_is_refused_on_the_bypass_path(tmp_path: Path) -> None:
    """That path keeps no in-flight state, so there would be nothing to wait on.

    ADR-0025 §1: the bypass is a cold one-shot that creates nothing under
    `.review/session` — no lock and no round marker. `--start` refuses rather than
    handing back a handle to a round nothing can observe or attribute to a tree.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)

    result = _run(repo, _env(tmp_path, GITHUB_ACTIONS="true"), "--start", "adversarial", "main")

    assert result.returncode == USAGE
    assert "--start is unavailable on the bypass path" in result.stderr
    assert not (repo / ".review" / "session").exists()


def test_wait_still_reports_a_finished_bypass_round(tmp_path: Path) -> None:
    """An artifact is selected by its recorded tree, which every path records."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    run_review(repo, tmp_path, GITHUB_ACTIONS="true")

    env = _env(tmp_path, GITHUB_ACTIONS="true")
    result = _run(repo, env, "--wait", "adversarial", "main", "--timeout", "0")

    assert result.returncode == RECORDED, result.stderr
    assert _fields(result.stdout)["verdict"] == "APPROVE"
    assert not (repo / ".review" / "session").exists()


def test_two_simultaneous_starts_leave_one_round_and_one_success(tmp_path: Path) -> None:
    """Only one child can claim the persona lock; only one parent may claim success.

    `--start` reads whether a round is in flight and then writes one, and two
    invocations interleaving between those steps both launch. Exactly one round
    runs either way — the loser's child is refused by `_claim_persona` — but the
    loser's parent must not report 0 for a child that was refused, and must not
    truncate the winner's log out from under it. The start lock and the
    per-attempt token are what make the report match the fact.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    release = tmp_path / "let-the-round-finish"
    env = _env(tmp_path, FAKE_CODEX_PRE_CMD=_hold_round_until(release))
    both_ready = threading.Barrier(2)

    def start() -> subprocess.CompletedProcess[str]:
        both_ready.wait()
        return _run(repo, env, "--start", "adversarial", "main")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in [pool.submit(start), pool.submit(start)]]

    codes = sorted(result.returncode for result in results)
    assert codes[0] == 0, [r.stderr for r in results]
    assert codes[1] != 0, "the second start reported success for a round it did not launch"
    winner = next(result for result in results if result.returncode == 0)
    # The marker belongs to the winner's own child, which is what the token buys.
    assert _round_pids(repo) == [int(_fields(winner.stdout)["pid"])]

    release.touch()
    _reap(repo)
    assert len(list((repo / ".review").glob("*.md"))) == 1


@pytest.mark.parametrize("value", ["0", "not-a-number", "030", "-1", "5s"])
def test_a_start_grace_that_cannot_be_waited_out_is_refused(tmp_path: Path, value: str) -> None:
    """Zero is refused with the malformed values, not accepted as "do not wait".

    `--start`'s contract is that it returns once the round has claimed its loop, so
    a zero-second budget for that is a contradiction — and it does not fail
    harmlessly: the deadline is already past on the first pass, so the start would
    report a round that "is not running" while its child ran on behind the message.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    env = _env(tmp_path)
    env["CODEX_REVIEW_START_GRACE"] = value

    result = _run(repo, env, "--start", "adversarial", "main")

    assert result.returncode == USAGE, result.stderr
    assert "CODEX_REVIEW_START_GRACE" in result.stderr
    # Refused before anything was launched: no round, no marker, no log.
    assert _round_pids(repo) == []
    assert not list((repo / ".review").glob("*.md"))


def test_start_pins_the_base_commit_for_its_child(tmp_path: Path) -> None:
    """The child is handed a commit, not the ref, so the two cannot resolve apart.

    A ref is mutable. If a fetch landed between the parent's `git merge-base` and
    the child's, the child would key its lock, marker and artifact under a
    different loop and the parent would poll its own key until the grace expired —
    reporting failure while the paid round ran on and recorded an artifact
    somewhere the parent never looked. Passing the resolved commit closes that
    window by construction, and `--wait`, which resolves the ref for itself, still
    finds the round: that agreement is the invariant this protects.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    env = _env(tmp_path)
    merge_base = _git(repo, "merge-base", "main", "HEAD")

    assert _run(repo, env, "--start", "adversarial", "main").returncode == 0
    waited = _run(repo, env, "--wait", "adversarial", "main", "--timeout", "60")

    assert waited.returncode == RECORDED, waited.stderr
    provenance = (repo / _fields(waited.stdout)["artifact"]).read_text().splitlines()[0]
    # `base=` is the ref for a foreground round and the pinned commit here.
    assert f" base={merge_base} " in provenance
    assert f" base_sha={merge_base} " in provenance


def _bin_without_flock(tmp_path: Path) -> str:
    """A PATH with the tools the driver needs up to its `flock` probe, minus flock.

    `flock` ships in the same directory as `git` on every host this runs on, so
    the absence has to be built rather than found: a directory of symlinks to the
    tools that are wanted, and no link for the one that is not.
    """
    bin_dir = tmp_path / "no-flock-bin"
    bin_dir.mkdir()
    wanted = [
        "git",
        "bash",
        "sh",
        "sed",
        "awk",
        "grep",
        "head",
        "tail",
        "date",
        "cat",
        "mktemp",
        "tr",
        "sort",
        "wc",
        "rm",
        "mv",
        "od",
        "find",
        "sleep",
        "uname",
        "cut",
        "dirname",
        "basename",
        "ls",
        "kill",
        "touch",
        "sha1sum",
        "setsid",
        "nohup",
    ]
    for tool in wanted:
        found = shutil.which(tool)
        if found is not None:
            (bin_dir / tool).symlink_to(found)
    install_fake_codex(tmp_path / "bin")
    (bin_dir / "codex").symlink_to(tmp_path / "bin" / "codex")
    return str(bin_dir)


def test_start_is_refused_where_there_is_no_flock(tmp_path: Path) -> None:
    """Without a lock, two detached rounds of one persona could not be prevented.

    `_claim_persona` claims nothing when `flock` is absent — the pre-#142
    degradation this script keeps on purpose — so two `--start`s would each launch
    a round and each observe its own token in the marker they take turns
    overwriting. Both would report success, and both would write one artifact, one
    thread and one snapshot. The foreground form keeps the degradation because an
    operator runs one command at a time; `--start` returns immediately and is the
    affordance that makes two easy to launch by accident.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    env = _env(tmp_path)
    env["PATH"] = _bin_without_flock(tmp_path)
    if shutil.which("flock", path=env["PATH"]) is not None:
        pytest.skip("could not build a PATH without flock")

    result = _run(repo, env, "--start", "adversarial", "main")

    assert result.returncode == USAGE, result.stderr
    assert "--start is unavailable without 'flock'" in result.stderr
    # Refused before launching: no round, no artifact.
    assert _round_pids(repo) == []
    assert not list((repo / ".review").glob("*.md"))


def test_wait_finds_a_round_whose_base_ref_moved_under_it(tmp_path: Path) -> None:
    """The loop key folds in the base, so a base move re-files a running round.

    ADR-0025 §1 keys the loop on `(branch, base)` deliberately — a moved base is a
    different diff and must not inherit a session — so a base that moves while a
    round runs files that round under a key `--wait` no longer computes. Reading
    one path would then answer "no round is in flight" about a round plainly alive
    on disk, and the caller, told never to poll an exit 4, would start a
    replacement round it did not need.

    The ref really is moved here, forward into HEAD's own history, rather than
    simulated by passing a different base argument.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "three\n", "second change")
    release = tmp_path / "let-the-round-finish"
    env = _env(tmp_path, FAKE_CODEX_PRE_CMD=_hold_round_until(release))

    assert _run(repo, env, "--start", "adversarial", "main").returncode == 0
    started_base = _git(repo, "merge-base", "main", "HEAD")
    _git(repo, "branch", "-f", "main", "HEAD~1")
    assert _git(repo, "merge-base", "main", "HEAD") != started_base

    waited = _run(repo, env, "--wait", "adversarial", "main", "--timeout", "2")

    assert waited.returncode == STILL_RUNNING, waited.stderr
    assert "still running" in waited.stderr
    assert started_base[:12] in waited.stderr, "the moved base is named, not hidden"

    # And nothing is lost: the round records an artifact for HEAD's tree under the
    # older base, and `--wait` reports it.
    release.touch()
    settled = _run(repo, env, "--wait", "adversarial", "main", "--timeout", "60")
    assert settled.returncode == RECORDED, settled.stderr
    assert _fields(settled.stdout)["tree"] == _tree(repo)


def test_a_newer_round_on_another_tree_does_not_hide_the_one_covering_head(
    tmp_path: Path,
) -> None:
    """Two rounds of one persona can be live at once, under different base keys.

    Picking the newest live marker and then judging its tree would let a newer
    round on some other tree hide an older one covering HEAD exactly — answering
    exit 4, "stop polling", about the very round that is about to record the
    artifact being waited for. A marker covering HEAD's tree wins outright.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "three\n", "second change")
    covered_sha = _git(repo, "rev-parse", "HEAD")
    covered_tree = _tree(repo)
    release = tmp_path / "let-the-rounds-finish"
    env = _env(tmp_path, FAKE_CODEX_PRE_CMD=_hold_round_until(release))

    # Round one: HEAD's current tree, against the original base.
    assert _run(repo, env, "--start", "adversarial", "main").returncode == 0

    # The base moves, so a second round of this persona files under a new loop
    # key and can be live alongside the first — on a different, newer tree.
    _git(repo, "branch", "-f", "main", "HEAD~1")
    _commit(repo, "four\n", "third change")
    assert _run(repo, env, "--start", "adversarial", "main").returncode == 0

    # HEAD returns to the tree the OLDER round is covering.
    _git(repo, "reset", "--hard", "-q", covered_sha)
    assert _tree(repo) == covered_tree
    assert len(list((repo / ".review" / "session").glob("*.adversarial.round"))) == 2

    waited = _run(repo, env, "--wait", "adversarial", "main", "--timeout", "2")

    assert waited.returncode == STILL_RUNNING, waited.stderr
    assert "still running" in waited.stderr
    release.touch()
    _reap(repo)


def test_another_loops_round_cannot_mask_this_loops_starting_round(
    tmp_path: Path,
) -> None:
    """A held lock with no marker yet is a round starting, not a round elsewhere.

    `_claim_persona` clears the previous marker on the way in and republishes once
    the identity settles, so for about a second every round has a held lock and no
    marker. If an unrelated live round on another tree supplied the tree during
    that window, `--wait` would answer exit 4 — "stop polling" — about the round
    that is starting, which is the foreground-cutoff shape this mode exists for.

    The window is reproduced exactly: the marker is removed from disk while its
    round holds the lock, which is the on-disk state `_claim_persona` creates.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "three\n", "second change")
    release = tmp_path / "let-the-rounds-finish"
    env = _env(tmp_path, FAKE_CODEX_PRE_CMD=_hold_round_until(release))

    # An unrelated round, on another tree, under an older base key.
    assert _run(repo, env, "--start", "adversarial", "main").returncode == 0
    _git(repo, "branch", "-f", "main", "HEAD~1")
    _commit(repo, "four\n", "third change")

    # This loop's round, then rewound into its own publication window.
    assert _run(repo, env, "--start", "adversarial", "main").returncode == 0
    session = repo / ".review" / "session"
    markers = sorted(session.glob("*.adversarial.round"), key=lambda m: m.stat().st_mtime)
    assert len(markers) == 2
    current = markers[-1]
    assert f"tree={_tree(repo)}" in current.read_text()
    current.unlink()

    waited = _run(repo, env, "--wait", "adversarial", "main", "--timeout", "2")

    assert waited.returncode == STILL_RUNNING, waited.stderr
    assert "still running" in waited.stderr
    release.touch()
    _reap(repo)
