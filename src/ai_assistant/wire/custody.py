"""The custody conditions on a path trusted rather than authenticated (ADR-0084 §1).

Three things are located by a path rather than authenticated: the hub's data
directory, which holds the seven stores and the instance lock; the hub's overlay
agent socket, whose answer ADR-0124 §4 makes the identity of every device that
connects; and — §4's second clause, from the other end of the hop — the *client's*
overlay agent socket, whose answer decides whether the destination it is about to
dial is the hub it was enrolled at. None has a handshake to fall back on at the
moment it is opened, so all three depend on the same property of the filesystem —
**that no untrusted user can replace the entry that is about to be opened**.

That property is a walk over the ancestors, and this module owns it so the callers
cannot drift apart on a security rule. Only the *predicate* is shared. Each caller
phrases its own refusal, because what an operator should do about a bad path
differs entirely between "move the data directory" and "point the agent socket
elsewhere", and a message that served both would help with neither.

**Why this is in ``wire`` and not in ``service``**, which is where it was written
(#911, #937). ADR-0084 §6 rules that ``wire`` "depends on ``core`` and nothing
else", and ADR-0083 §8 that "nothing may import ``service``" — so a predicate
living in ``service`` is reachable by neither the wire client nor the CLI, and the
client half of ADR-0124 §4 could only have restated it a third time, which is the
drift hazard this module exists to prevent. ``wire`` is the lowest package all
three callers can name: both ``service`` callers already import
:mod:`ai_assistant.wire.address`, and so does the CLI. It is not in ``core``
because ``core`` holds contracts, types, configuration and errors, and a
filesystem walk is none of those.

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


def displayable(path: Path | str | bytes | None) -> str:
    """An OS-supplied value rendered so a refusal naming it can itself be built.

    :mod:`ai_assistant.core.types` requires message text to have a UTF-8 encoding,
    and gives the reason this function exists: "interpolating it raw would build an
    error message that is itself unencodable, so reporting the fault would fail the
    same way the fault does". A pathname is exactly such a value — on Unix it is
    bytes, and a non-UTF-8 one reaches Python as PEP 383 surrogates — so it is
    escaped for display rather than echoed, and the operator still sees which path
    was meant.

    **Everything the OS hands back goes through here, not only the argument.**
    ``OSError.filename`` is the one that is easy to miss — it is as much a pathname
    as the argument, it is ``None`` when the platform supplied none, and
    interpolating it raw reintroduces the identical fault one line from where it
    was fixed. ``OSError.strerror`` is decoded with the locale encoding and can
    carry surrogates for the same reason, so it takes the same treatment; escaping
    a string that never needed it costs nothing, and the failure it prevents is a
    refusal that cannot be reported.

    **It sits beside the custody walk because the two always travel together**, and
    #940 asked for exactly this once a third caller existed. Every refusal built on
    a custody verdict names the path it was decided about, so a module that can
    reach the predicate and not the renderer would rebuild the renderer — which is
    how the ``sun_path`` measurement in :mod:`ai_assistant.wire.address` came to
    carry the bug the walk's own copy had already fixed.

    Args:
        path: A pathname, an ``errno`` string, or ``None`` where the platform
            supplied no value at all.

    Returns:
        Text with a UTF-8 encoding, with any byte that has no character escaped.
    """
    if path is None:
        return "an unnamed path"
    return os.fsencode(path).decode("utf-8", "backslashreplace")


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


def others_can_create_in(directory: Path) -> bool:
    """Whether a user other than the owner can add a *new* entry to ``directory``.

    **The sticky bit does not bear on this, and that is why it is asked
    separately.** Sticky stops a user removing or renaming an entry they do not
    own, and a name that does not exist yet is neither owned nor removable. So
    ``/tmp`` is a safe place to keep something that already exists and an unsafe
    place to leave a name unclaimed for something that does not — a distinction
    :func:`first_ancestor_fault` deliberately cannot make, because for the entries
    it walks over the sticky bit is exactly the right answer.

    Args:
        directory: The directory an entry would be created in.

    Returns:
        ``True`` when the group or other write bit is set, sticky or not.

    Raises:
        OSError: If the directory cannot be stat'ed.
    """
    return bool(directory.stat().st_mode & _WRITABLE_BY_OTHERS)


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
