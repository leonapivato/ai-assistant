"""The deploy lock of ``scripts/deploy_hub.py``, run in a real shell (#3262).

The box's half of the lock is shell, so it is run here, by ``sh``, against real
files and the real ``flock``: the holder that :meth:`Plan.hold_lock` sends, held by
the same :func:`_hold` a deploy holds it with, and :data:`FENCE` around a command.
What stands in for the box is a home directory under ``tmp_path``, a ``su`` that
runs its command as this user there, and a directory standing in for ``/run``.
Nothing here contacts a box: ``sh -c`` takes the place of ``ssh``.
"""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _operator_recipes import load

_MODULE = load("deploy_hub")

pytestmark = pytest.mark.skipif(
    shutil.which("sh") is None or shutil.which("flock") is None,
    reason="needs a POSIX sh and util-linux flock",
)

#: ``su - <user> -c <command>``, as the service user's login shell would run it:
#: in its home, here this user's own.
_SU = """#!/bin/sh
[ "$1" = - ] && [ "$3" = -c ] || { echo "su: unexpected $*" >&2; exit 2; }
cd "$HOME" && exec sh -c "$4"
"""


class _Box:
    """A service user's home, a ``/run``, and the plans of deploys to them."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.home = tmp_path / "home"
        self.run = tmp_path / "run"
        shims = tmp_path / "shims"
        for directory in (self.home, self.run, shims):
            directory.mkdir()
        (shims / "su").write_text(_SU)
        (shims / "su").chmod(0o755)
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.setenv("PATH", f"{shims}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("SHELL", shutil.which("sh") or "/bin/sh")
        monkeypatch.setattr(_MODULE, "_OWNER_DIR", str(self.run))
        self.lock = self.home / ".deploy-lock"
        self.owner = self.run / "deploy-hub-assistant.owner"

    def plan(self) -> Any:
        """A deploy's plan, with a token of its own."""
        parsed = _MODULE._parser().parse_args(["hub.example"])
        return _MODULE.Plan(parsed, "w.whl")

    def hold(self, plan: Any) -> Any:
        """Take the lock as a deploy does, with ``sh -c`` in place of ssh."""
        return _MODULE._hold(["sh", "-c", plan.hold_lock()], plan.lock_said)

    def lock_is_free(self) -> bool:
        """Whether a taker other than a deploy, the nightly backup, could have it now."""
        completed = subprocess.run(  # noqa: S603  # fixed argv, test-built path
            [shutil.which("flock") or "flock", "--nonblock", str(self.lock), "true"],
            check=False,
        )
        return completed.returncode == 0


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Box:
    return _Box(tmp_path, monkeypatch)


@pytest.mark.timeout(30)
def test_the_holder_holds_the_lock_until_it_is_released(box: _Box) -> None:
    plan = box.plan()

    lease = box.hold(plan)

    assert isinstance(lease, _MODULE.ProcessLease), lease
    assert lease.held()
    assert not box.lock_is_free()
    assert box.owner.read_text() == f"{plan.token}\n"
    lease.release()
    assert not lease.held()
    assert box.lock_is_free()


@pytest.mark.timeout(30)
def test_a_second_deploy_is_refused_at_once_while_the_first_holds_it(box: _Box) -> None:
    first = box.hold(box.plan())
    try:
        refused = box.hold(box.plan())
    finally:
        first.release()

    assert refused[0] == _MODULE._BUSY, refused


@pytest.mark.timeout(30)
def test_a_deploy_is_refused_while_the_nightly_backup_holds_the_lock(box: _Box) -> None:
    # The backup takes the same flock on the same file, as anything else may.
    box.lock.touch()
    with box.lock.open("rb") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        refused = box.hold(box.plan())

    assert refused[0] == _MODULE._BUSY, refused
    assert not box.owner.exists()


@pytest.mark.timeout(30)
def test_a_directory_where_the_lock_goes_is_refused(box: _Box) -> None:
    box.lock.mkdir()

    refused = box.hold(box.plan())

    assert refused[0] == _MODULE._LEGACY, refused
    assert not box.owner.exists()


@pytest.mark.timeout(30)
def test_a_holder_that_cannot_name_its_run_lets_the_lock_go(
    box: _Box, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The service user's half holds the lock and still reads; the root half's
    # answer is what ends the session, rather than a deploy waiting on it forever.
    monkeypatch.setattr(_MODULE, "_OWNER_DIR", str(box.run / "missing"))

    refused = box.hold(box.plan())

    assert refused[0] == 1, refused
    assert box.lock_is_free()


@pytest.mark.timeout(30)
def test_the_holder_waits_for_a_command_a_dead_deploy_left_running(box: _Box) -> None:
    taken: list[Any] = []
    box.owner.touch()
    with box.owner.open("rb") as running:
        fcntl.flock(running, fcntl.LOCK_EX)
        holder = threading.Thread(target=lambda: taken.append(box.hold(box.plan())))
        holder.start()
        time.sleep(0.5)
        assert holder.is_alive(), taken
    holder.join(20)

    assert isinstance(taken[0], _MODULE.ProcessLease), taken
    taken[0].release()


def _fenced(plan: Any, command: str) -> subprocess.CompletedProcess[str]:
    """Run one box command as a deploy holding the lock sends it, ssh aside."""
    return subprocess.run(  # noqa: S603  # fixed shell, test-built command
        [shutil.which("sh") or "sh", "-c", plan.fence(command)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.timeout(30)
def test_a_command_runs_under_the_owner_files_lock_while_its_run_holds_the_lock(
    box: _Box,
) -> None:
    plan = box.plan()
    lease = box.hold(plan)
    try:
        ran = _fenced(plan, f"echo ran; flock --nonblock {box.owner} true; echo $?")
    finally:
        lease.release()

    assert ran.returncode == 0, ran.stderr
    # The owner file's flock is held while the command runs, so no holder can
    # take the lock over from under it.
    assert ran.stdout == "ran\n1\n"


@pytest.mark.timeout(30)
def test_a_command_runs_as_the_login_shell_would_have_run_it(box: _Box) -> None:
    plan = box.plan()
    lease = box.hold(plan)
    try:
        ran = _fenced(plan, "printf '%s|' ~/x 'a b' \"$(echo c)\"")
    finally:
        lease.release()

    assert ran.stdout == f"{box.home}/x|a b|c|", ran.stderr


@pytest.mark.timeout(30)
def test_a_command_from_a_deploy_another_holder_took_over_from_is_refused(box: _Box) -> None:
    dead = box.plan()
    box.hold(dead).release()
    later = box.hold(box.plan())
    try:
        late = _fenced(dead, "echo ran")
        with pytest.raises(_MODULE.LockLost, match="the box refused this deploy's command"):
            _MODULE._run_local(["sh", "-c", dead.fence("echo ran")])
    finally:
        later.release()

    assert late.returncode == _MODULE._FENCED
    assert _MODULE._FENCED_SAID in late.stderr
    assert "ran" not in late.stdout


@pytest.mark.timeout(30)
def test_the_lock_file_is_the_service_users_and_its_existence_means_nothing(box: _Box) -> None:
    box.hold(box.plan()).release()

    assert box.lock.is_file()
    assert box.lock.stat().st_uid == os.getuid()
    # A lock file left behind is no lock: the next deploy takes it.
    lease = box.hold(box.plan())
    assert isinstance(lease, _MODULE.ProcessLease), lease
    lease.release()
