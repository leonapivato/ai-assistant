"""The data directory is a security boundary, not just a location (ADR-0084 §1).

**The gap this closes is not obvious and the obvious fix does not close it.**
Every file the hub puts in the data directory is created owner-only already
(ADR-0004 §4), and that restricts *opening* those files. It does nothing about
the **directory entry**. If ``data_dir`` is group- or world-writable, another
local user can unlink a database or a socket and put their own in its place;
under ADR-0084 §9 the CLI then derives the same path, connects, and hands over
the utterance. Mode on the replaced file never comes into it.

Securing the leaf alone is likewise insufficient, and ADR-0084 §1 gives the
counter-example: ``data_dir=/srv/shared/alice`` at ``0700`` with ``/srv/shared``
at ``0777`` and not sticky — another user renames ``alice``, creates their own
directory at the configured path, and the leaf's mode is irrelevant because the
leaf is gone.

So the whole chain is checked, at ADR-0083 §3's **step 2**, where §1 places it:
before the lock, before any store is opened, and long before a client could
derive anything from the path. Every failure is a ``ConfigurationError`` and
therefore a stay-down exit — none of them is fixed by restarting.

**The ancestors get a weaker condition than the leaf, deliberately.** Requiring
hub-uid ownership all the way up would reject the ordinary default, since ``/``
and ``/home`` are root-owned and always will be, and a rule that fails the
deployment everyone actually runs is not a security control but an outage. What
matters about an ancestor is whether an untrusted user can *replace* the entry
below it — which is exactly what the sticky bit prevents, and why an
other-writable ancestor carrying it (``/tmp``) is accepted.

**The fourth condition is a length, and it is here for the same reason** (#554).
ADR-0084 §1 puts the ``sun_path`` budget at this step too: "a perfectly writable,
perfectly valid data directory can have a path no socket can be bound inside", and
left unchecked that failure lands at ADR-0083 §3's **step 6** — after the lock is
held, the seven stores are open and the start-up sweeps have run. It is a property
of ``data_dir`` rather than of the listener, which is why it sits beside the other
three rather than in :mod:`ai_assistant.service.transport`.

**What this is not.** ADR-0084 §1 is explicit that a filesystem walk "can be
wrong — a bind mount, an ACL, a symlinked ancestor" and that what actually closes
the hole is the client authenticating the *server* from the kernel's peer
credentials after connecting. That belongs to the transport lane. These
conditions stay as defence in depth, and because the seven databases in this
directory have no handshake to fall back on.
"""

from __future__ import annotations

import os
import stat
from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.wire.address import check_socket_path
from ai_assistant.wire.custody import first_ancestor_fault

if TYPE_CHECKING:
    from pathlib import Path

#: The mode the hub creates its data directory with — owner-only, ADR-0004 §4's
#: posture applied to the container rather than only to its contents.
_OWNER_ONLY_DIR: Final = 0o700

#: The bits that let somebody other than the owner add, remove or rename entries.
_WRITABLE_BY_OTHERS: Final = stat.S_IWGRP | stat.S_IWOTH


def prepare(data_dir: Path) -> None:
    """Create the data directory if it is absent, then validate the whole chain.

    ADR-0083 §3's step 2, in the order the ADRs fix it: create, then check the
    leaf, then check every ancestor, then check that the path can hold the socket.
    Creating first is what makes the leaf check meaningful on a fresh deployment:
    there is nothing to validate until the directory exists, and a hub that refused
    to start because its directory was missing would fail every first run.

    **An existing directory is validated, never repaired.** Silently widening or
    narrowing a mode the operator set would hide the misconfiguration rather than
    report it, and ADR-0084 §1 says the directory is "created ``0700`` **when the
    hub creates it**" — so the mode is imposed only on a directory this call
    brought into existence.

    Args:
        data_dir: The absolute, canonical data directory
            (:class:`~ai_assistant.core.config.Settings` guarantees both).

    Raises:
        ConfigurationError: If the directory or any ancestor fails ADR-0084 §1's
            conditions, or the socket path exceeds this platform's ``sun_path``
            budget (#554). Raised as this class so ADR-0083 §5's mapping reaches it
            through the same type check every other startup misconfiguration
            takes — none of these is fixed by restarting.
        OSError: If the directory cannot be created at all. Left to propagate,
            because the raw errno is what distinguishes a stay-down filesystem
            access fault from a transient one (ADR-0083 §3 step 3, §5).
    """
    try:
        data_dir.mkdir(parents=True, mode=_OWNER_ONLY_DIR)
    except FileExistsError:
        pass
    else:
        # `mkdir`'s mode argument is masked by the process umask, so the
        # directory it just made may be wider than asked for. `chmod` is not
        # masked, and this runs only on a directory that did not exist a moment
        # ago and is therefore unambiguously ours.
        data_dir.chmod(_OWNER_ONLY_DIR)

    _check_leaf(data_dir)
    _check_ancestors(data_dir)
    check_socket_path(data_dir)


def _check_leaf(data_dir: Path) -> None:
    """The data directory is a directory, owned by us, and not writable by others."""
    info = data_dir.stat()
    if not stat.S_ISDIR(info.st_mode):
        msg = (
            f"the data directory {data_dir} is not a directory; move whatever occupies "
            f"that path, or configure ASSISTANT_DATA_DIR elsewhere"
        )
        raise ConfigurationError(msg)
    if info.st_uid != os.geteuid():
        msg = (
            f"the data directory {data_dir} is owned by uid {info.st_uid}, not by "
            f"uid {os.geteuid()} which the hub runs as; another user's directory holds "
            f"the seven databases and the instance lock, so the hub will not open them"
        )
        raise ConfigurationError(msg)
    if info.st_mode & _WRITABLE_BY_OTHERS:
        msg = (
            f"the data directory {data_dir} is mode {stat.S_IMODE(info.st_mode):04o} and "
            f"writable by other users, who could replace the databases inside it; "
            f"chmod it to 0700"
        )
        raise ConfigurationError(msg)


def _check_ancestors(data_dir: Path) -> None:
    """No ancestor lets an untrusted user replace the entry beneath it.

    The condition itself lives in :mod:`ai_assistant.wire.custody`, shared with
    the overlay agent's socket, which depends on the same property for the same
    reason (ADR-0124 §4). Only the wording is chosen here — what an operator should
    do about an untrustworthy ancestor is different for a data directory than for a
    daemon's socket, so each caller phrases its own refusal.
    """
    fault = first_ancestor_fault(data_dir)
    if fault is None:
        return
    if fault.kind == "replaceable":
        msg = (
            f"{fault.ancestor} is mode {fault.mode:04o}, writable by other "
            f"users and not sticky, so another user could rename or replace the path "
            f"below it and the data directory's own mode would not apply; chmod it, "
            f"set its sticky bit, or move the data directory"
        )
        raise ConfigurationError(msg)
    msg = (
        f"{fault.ancestor} is owned by uid {fault.uid}, neither root nor the "
        f"uid {os.geteuid()} the hub runs as, so that user controls the path to the "
        f"data directory; move the data directory under one you own"
    )
    raise ConfigurationError(msg)
