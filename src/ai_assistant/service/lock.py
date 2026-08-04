"""The instance lock: exactly one hub per data directory (ADR-0083 §1, §10).

Exclusivity is a **ruling**, not an optimisation — the hub is the only process
that opens the six SQLite databases, and the API is the only door. Two mechanisms
enforce it and this is the first: an exclusive advisory ``flock`` that stops a
second *hub*. The second is a ``lint-imports`` contract, which stops the in-repo
route to a second opener; ADR-0083 §10 sequences half of that with the lane that
makes the CLI a client, so only the ``everything → service`` half lands with this
package.

**Why ``flock`` and not a pid file.** The kernel releases the lock when the holder
dies, however it dies, so there is no stale-lock problem and no PID-liveness
heuristic to get wrong: **a held lock always means a live holder.** That single
property is what lets ADR-0083 §1 classify contention as restartable — the holder
is either serving or draining, and both resolve with nobody acting.

Two limits are named rather than papered over. The lock is **advisory**, so it
stops a second hub and not an arbitrary process; and it is **unreliable on network
filesystems**, which is one of the two reasons ADR-0083 §3's D3 requires the data
directory to be on local storage.
"""

from __future__ import annotations

import errno
import fcntl
import os
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

#: The lock file's name inside the data directory (ADR-0083 §1).
LOCK_FILENAME: Final = "hub.lock"

#: Owner-only, like every other file the hub puts in the data directory
#: (ADR-0004 §4). Applied with ``fchmod`` after acquiring rather than trusted to
#: ``os.open``'s mode argument, which the process umask masks and which does
#: nothing at all when the file already exists from a previous run.
_LOCK_FILE_MODE: Final = 0o600

#: The two ``errno`` values ``flock(LOCK_EX | LOCK_NB)`` uses for "somebody else
#: holds this". POSIX allows either, so both are treated as contention — and
#: nothing else is, which is what keeps a genuine permission fault on the lock
#: file from being misreported as a live peer.
_CONTENTION_ERRNOS: Final = frozenset({errno.EACCES, errno.EAGAIN})


class InstanceLock:
    """An exclusive advisory lock on ``<data_dir>/hub.lock``.

    Taken **before any store is opened** and held, unexamined, for the process's
    whole life (ADR-0083 §1, §3 step 2). Because taking it means opening a file
    for writing inside the data directory, acquiring is also the directory's
    writability check — necessary but not sufficient, which is why ADR-0083 §3
    keeps mapping filesystem access faults to a stay-down exit further down the
    startup sequence too.

    Not reentrant and not thread-safe: one process, one hub, one lock.
    """

    def __init__(self, path: Path) -> None:
        """Name the lock file without touching it.

        Args:
            path: The lock file, normally ``<data_dir>/hub.lock``. Its parent must
                exist by the time :meth:`acquire` is called.
        """
        self._path = path
        self._fd: int | None = None

    @property
    def path(self) -> Path:
        """The lock file's path, for a diagnostic that must name it."""
        return self._path

    @property
    def held(self) -> bool:
        """Whether this object currently holds the lock."""
        return self._fd is not None

    def acquire(self) -> bool:
        """Try once to take the lock, and record this process's pid if it succeeds.

        Non-blocking by construction: ``LOCK_NB`` means a contended lock returns
        immediately rather than parking a thread, so a caller owns the retry
        policy and the event loop is never blocked waiting on a peer.

        **The pid is written after acquiring, and that ordering is why the
        diagnostic hedges.** ``flock`` exposes no portable query for its holder, so
        the holder records its own pid — which means a contender can read the file
        empty (this process was pre-empted between the two calls) or stale (a
        previous holder's, not yet overwritten). :meth:`recorded_pid` therefore
        returns a hint, never a fact.

        Returns:
            ``True`` if the lock is now held, ``False`` if another instance holds
            it.

        Raises:
            OSError: If the lock file cannot be opened at all — a directory this
                process may not write into, a read-only filesystem, a path that is
                not a directory. Deliberately **not** caught and converted:
                ADR-0083 §3 needs it distinguishable from contention, because the
                two get opposite exit codes.
            RuntimeError: If this object already holds the lock. A second acquire
                would leak the first descriptor, and silently re-taking a lock one
                already holds is the shape of bug this class exists to prevent.
        """
        if self._fd is not None:
            msg = f"the instance lock on {self._path} is already held by this object"
            raise RuntimeError(msg)
        # O_RDWR because the pid is written; never O_TRUNC, which would destroy a
        # live holder's recorded pid *before* this process learns it cannot have
        # the lock. O_CLOEXEC so the lock is not inherited by anything this
        # process might later exec, which would keep the data directory locked
        # after the hub itself had exited.
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, _LOCK_FILE_MODE)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in _CONTENTION_ERRNOS:
                return False
            raise
        try:
            os.fchmod(fd, _LOCK_FILE_MODE)
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode())
            os.fsync(fd)
        except OSError:
            # The lock is held but unusable as a diagnostic source. Release rather
            # than continue: a half-initialised lock file would advertise a pid
            # that is not this process's, which is worse than none (§1).
            os.close(fd)
            raise
        self._fd = fd
        return True

    def release(self) -> None:
        """Release the lock by closing its descriptor. Idempotent.

        **The file is deliberately not unlinked.** Removing it would let a
        contender that has already opened the same inode take a lock on a file no
        longer at that path, and a third process could then create and lock a
        fresh one — two hubs, both believing they hold the directory. The file
        left behind costs nothing: the kernel's lock, not the file's existence, is
        what exclusivity rests on.
        """
        if self._fd is None:
            return
        os.close(self._fd)
        self._fd = None

    def recorded_pid(self) -> int | None:
        """The pid the current holder recorded, if one can be read (advisory).

        Returns:
            The pid, or ``None`` when the file is absent, empty, unreadable or
            does not parse. Every one of those is expected rather than
            exceptional — see :meth:`acquire` for why — so a diagnostic must treat
            a result as a hint and must not promise one. ADR-0083 §1 is explicit
            that "a diagnostic that unconditionally promises a pid would eventually
            print a wrong one, and a wrong pid in an operator message is worse than
            none".
        """
        try:
            recorded = self._path.read_text(encoding="utf-8").strip()
        except OSError, UnicodeDecodeError:
            return None
        try:
            return int(recorded)
        except ValueError:
            return None
