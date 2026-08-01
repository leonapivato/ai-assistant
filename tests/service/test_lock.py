"""One hub per data directory, enforced by the kernel (ADR-0083 §1, §10).

Exclusivity is what ADR-0014 §4's recovery presumption rests on — "presumes no
executor is live for those states" becomes true *by construction* rather than by
being a single-user assumption — and it is what lets ADR-0083 §12 defer a lease,
WAL, and the stores' concurrent-access posture. So these tests are not about a
file: they are about the one property those deferrals are standing on.

The tests that matter most are the ones about what a *contender* can observe,
because that is where the appealing implementation goes wrong. A pid file with a
liveness check has a stale-lock problem and a race; ``flock`` has neither, at the
price of exposing no portable way to ask who holds it — which is why the pid here
is written after acquiring and is read back as a hint that may be absent or stale.
"""

from __future__ import annotations

import os
import stat
from typing import TYPE_CHECKING

import pytest

from ai_assistant.service.lock import LOCK_FILENAME, InstanceLock

if TYPE_CHECKING:
    from pathlib import Path


def test_the_first_instance_takes_the_lock(tmp_path: Path) -> None:
    lock = InstanceLock(tmp_path / LOCK_FILENAME)

    assert lock.acquire()
    assert lock.held
    lock.release()


def test_a_second_instance_is_refused_rather_than_blocked(tmp_path: Path) -> None:
    """``LOCK_NB`` is what makes contention a *return value*, not a wait.

    A blocking acquire would park the process behind a peer that may be draining
    for an unbounded time (ADR-0083 §4 phase B), with no way to report why it had
    not started. Returning lets the caller bound its own retry and then exit with a
    code a supervisor understands.
    """
    holder = InstanceLock(tmp_path / LOCK_FILENAME)
    assert holder.acquire()
    contender = InstanceLock(tmp_path / LOCK_FILENAME)

    try:
        assert contender.acquire() is False
        assert not contender.held
    finally:
        holder.release()


def test_releasing_lets_the_next_instance_in(tmp_path: Path) -> None:
    """The case that makes contention *restartable* rather than fatal.

    ADR-0083 §1 classifies a contended lock as exit ``1`` because the holder is
    either serving or draining, and a drain ends. This is that ending: the moment
    it does, the next start succeeds with nobody having acted.
    """
    holder = InstanceLock(tmp_path / LOCK_FILENAME)
    assert holder.acquire()
    contender = InstanceLock(tmp_path / LOCK_FILENAME)
    assert contender.acquire() is False

    holder.release()

    assert contender.acquire()
    contender.release()


def test_release_is_idempotent(tmp_path: Path) -> None:
    """Shutdown runs it from a ``finally`` that may already have run."""
    lock = InstanceLock(tmp_path / LOCK_FILENAME)
    assert lock.acquire()

    lock.release()
    lock.release()

    assert not lock.held


def test_acquiring_twice_from_one_object_is_a_bug_and_says_so(tmp_path: Path) -> None:
    """Silently re-taking a held lock would leak the first descriptor.

    Worse than the leak: the leaked descriptor keeps the kernel lock alive
    independently of :meth:`release`, so a hub that had "released" would still be
    holding the directory and the next start would be refused forever. Refusing
    loudly is the only outcome that cannot become that.
    """
    lock = InstanceLock(tmp_path / LOCK_FILENAME)
    assert lock.acquire()

    try:
        with pytest.raises(RuntimeError, match="already held"):
            lock.acquire()
    finally:
        lock.release()


def test_the_holder_records_its_pid(tmp_path: Path) -> None:
    lock = InstanceLock(tmp_path / LOCK_FILENAME)
    assert lock.acquire()

    try:
        assert lock.recorded_pid() == os.getpid()
    finally:
        lock.release()


def test_the_pid_is_a_hint_and_its_absence_is_not_an_error(tmp_path: Path) -> None:
    """ADR-0083 §1 requires the diagnostic to degrade, not to fail.

    A contender can find the file empty — the holder was pre-empted between
    acquiring and writing — or holding a previous holder's pid. "A diagnostic that
    unconditionally promises a pid would eventually print a wrong one, and a wrong
    pid in an operator message is worse than none." So every unreadable shape has
    to come back as ``None`` rather than as an exception thrown while reporting a
    failure.
    """
    path = tmp_path / LOCK_FILENAME
    lock = InstanceLock(path)

    assert lock.recorded_pid() is None  # absent

    path.write_text("", encoding="utf-8")
    assert lock.recorded_pid() is None  # empty

    path.write_text("not-a-pid\n", encoding="utf-8")
    assert lock.recorded_pid() is None  # unparseable

    path.write_bytes(b"\xff\xfe\x00")
    assert lock.recorded_pid() is None  # not even text


def test_the_lock_file_is_owner_only(tmp_path: Path) -> None:
    """ADR-0004 §4 reaches this file like every other one in the data directory.

    ``fchmod`` after acquiring rather than trusting ``os.open``'s mode: the umask
    masks that argument, and it does nothing at all when the file already exists
    from a previous run — which, since the file is deliberately never unlinked, is
    the normal case rather than the exotic one.
    """
    path = tmp_path / LOCK_FILENAME
    path.write_text("stale\n", encoding="utf-8")
    path.chmod(0o666)
    lock = InstanceLock(path)

    assert lock.acquire()
    try:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        lock.release()


def test_the_lock_file_survives_release(tmp_path: Path) -> None:
    """Unlinking would break exclusivity rather than tidy up.

    A contender that has already opened the inode would take a lock on a file no
    longer at that path, and a third process could then create and lock a fresh
    one — two hubs, each satisfied it held the directory. Exclusivity rests on the
    kernel's lock, never on the file's existence, so the file simply stays.
    """
    path = tmp_path / LOCK_FILENAME
    lock = InstanceLock(path)
    assert lock.acquire()

    lock.release()

    assert path.exists()


def test_a_stale_pid_from_a_previous_run_is_overwritten(tmp_path: Path) -> None:
    """The file is never truncated before acquiring, and is always after.

    Truncating first would destroy a *live* holder's recorded pid on the way to
    discovering that the lock could not be taken — the contender would then report
    "held by another instance" with no pid, having just deleted the one it wanted.
    """
    path = tmp_path / LOCK_FILENAME
    path.write_text("999999\n", encoding="utf-8")
    lock = InstanceLock(path)

    assert lock.acquire()
    try:
        assert lock.recorded_pid() == os.getpid()
    finally:
        lock.release()


def test_a_contender_does_not_destroy_the_holders_pid(tmp_path: Path) -> None:
    """The other half of the same ordering, from the loser's side."""
    holder = InstanceLock(tmp_path / LOCK_FILENAME)
    assert holder.acquire()
    contender = InstanceLock(tmp_path / LOCK_FILENAME)

    try:
        assert contender.acquire() is False
        assert contender.recorded_pid() == os.getpid()
    finally:
        holder.release()


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses directory permissions")
def test_an_unwritable_directory_raises_rather_than_reporting_contention(
    tmp_path: Path,
) -> None:
    """The distinction the hub's exit code turns on (ADR-0083 §3 step 2, §5).

    Both faults can arrive as ``EACCES``, and they get **opposite** answers:
    contention is restartable because the holder resolves itself, while a
    directory this process may not write into never becomes writable by being
    opened again. Collapsing them either way is a real outage — a crash loop
    against an unchanging ``EACCES``, or a hub that refuses to restart because a
    healthy peer was serving.

    So contention is recognised only from ``flock``'s own failure, and anything
    that goes wrong *opening* the file is left to propagate.
    """
    sealed = tmp_path / "sealed"
    sealed.mkdir()
    sealed.chmod(0o500)
    lock = InstanceLock(sealed / LOCK_FILENAME)

    try:
        with pytest.raises(PermissionError):
            lock.acquire()
    finally:
        sealed.chmod(0o700)
