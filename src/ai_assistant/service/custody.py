"""The custody conditions on a path the hub trusts (ADR-0084 §1).

Two things the hub relies on are located by a path rather than authenticated: the
data directory, which holds the seven stores and the instance lock, and the
overlay agent's socket, whose answer ADR-0124 §4 makes the identity of every
device that connects. Neither has a handshake to fall back on at the moment it is
opened, so both depend on the same property of the filesystem — **that no
untrusted user can replace the entry the hub is about to open**.

That property is a walk over the ancestors, and this module owns it so the two
callers cannot drift apart on a security rule. Only the *predicate* is shared.
Each caller phrases its own refusal, because what an operator should do about a
bad path differs entirely between "move the data directory" and "point the agent
socket elsewhere", and a message that served both would help with neither.

**The ancestors get a weaker condition than any leaf, deliberately.** Requiring
hub-uid ownership all the way up would reject the ordinary deployment, since ``/``
and ``/run`` are root-owned and always will be. What matters about an ancestor is
whether an untrusted *third party* can replace the entry below it — which is
exactly what the sticky bit prevents, and why an other-writable ancestor carrying
it (``/tmp``) is accepted.

**What this is not.** ADR-0084 §1 is explicit that a filesystem walk "can be wrong
— a bind mount, an ACL, a symlinked ancestor". This is defence in depth, not the
thing that closes the hole; where a handshake exists it is what actually
authenticates the peer.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from pathlib import Path

#: The bits that let somebody other than the owner add, remove or rename entries.
_WRITABLE_BY_OTHERS: Final = stat.S_IWGRP | stat.S_IWOTH


@dataclass(frozen=True, slots=True)
class AncestorFault:
    """Why one ancestor of a path is not trustworthy.

    Attributes:
        ancestor: The offending directory.
        mode: Its permission bits, already reduced by :func:`stat.S_IMODE`.
        uid: The uid owning it.
        kind: ``"replaceable"`` when the directory is writable by others and not
            sticky, so a third party can rename or replace what sits beneath it;
            ``"foreign"`` when it is owned by neither root nor the running euid, so
            that user controls the path.
    """

    ancestor: Path
    mode: int
    uid: int
    kind: Literal["replaceable", "foreign"]


def first_ancestor_fault(path: Path) -> AncestorFault | None:
    """The nearest ancestor that lets an untrusted user replace the entry below it.

    The walk stops at the first fault rather than collecting every one: the
    operator has to fix this one before the next becomes reachable, and naming a
    single directory is what makes the refusal actionable.

    Args:
        path: The path whose ancestry is in question. It need not exist — only its
            parents are examined, which is what lets a caller check custody of a
            socket that a daemon has not yet created.

    Returns:
        The nearest offending ancestor, or ``None`` when every one of them is
        trustworthy.

    Raises:
        OSError: If an ancestor cannot be stat'ed. Left to propagate, because the
            raw errno distinguishes a path that is gone from one the process may
            not traverse, and the two have different fixes.
    """
    euid = os.geteuid()
    for ancestor in path.parents:
        info = ancestor.stat()
        # The sticky bit is precisely what stops a user removing or renaming an
        # entry they do not own, which is the only thing an ancestor's mode can
        # do to the entry below it.
        if info.st_mode & _WRITABLE_BY_OTHERS and not info.st_mode & stat.S_ISVTX:
            return AncestorFault(
                ancestor=ancestor,
                mode=stat.S_IMODE(info.st_mode),
                uid=info.st_uid,
                kind="replaceable",
            )
        if info.st_uid not in (0, euid):
            return AncestorFault(
                ancestor=ancestor,
                mode=stat.S_IMODE(info.st_mode),
                uid=info.st_uid,
                kind="foreign",
            )
    return None
