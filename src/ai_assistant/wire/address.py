"""Where the door is, and whether the path can hold it (ADR-0084 §1, §9).

**One setting locates both the data and the door.** The socket path derives from
:attr:`~ai_assistant.core.config.Settings.data_dir` as ``<data_dir>/hub.sock``, and
ADR-0084 §9 makes that deliberate: "a client that can find the data directory can
find the hub", and "a hub and a client that disagree about the data directory would
otherwise fail with a missing socket rather than with the misconfiguration they
actually have". ``Settings`` refuses a relative value and canonicalises the rest,
which is what makes "the same field" mean the same directory.

**The path is length-checked at startup, and this closes #554.** A pathname
``AF_UNIX`` socket is bounded by ``sun_path``, and a perfectly writable, perfectly
valid data directory can have a path no socket can be bound inside. Left unchecked
that failure lands at ADR-0083 §3's **step 6** — after the lock is held, the seven
stores are open and the start-up sweeps have run — "the latest and least legible
moment available, and a hub that is down for a reason buried in a ``bind`` errno is
ruling 4's failure".
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import ConfigurationError

if TYPE_CHECKING:
    from pathlib import Path

#: The socket's name inside the data directory (ADR-0084 §1).
SOCKET_FILENAME: Final[str] = "hub.sock"

#: Owner-only, which is ADR-0004 §4's existing posture applied to a new object of
#: the same kind rather than a control invented here — and on Linux the kernel
#: enforces it at ``connect()``, so ``0600`` on ``hub.sock`` is what makes a Unix
#: socket "reuse a ratified access control" where a TCP loopback port has none.
SOCKET_MODE: Final[int] = 0o600

#: ``sun_path``'s size, **by platform**, terminator included. ADR-0084 §1 requires
#: "the running platform's own limit rather than a constant": hardcoding 108 "would
#: let a 104-byte path pass validation on macOS and then fail at ``bind()``, which
#: is precisely the late, opaque failure this rule exists to prevent, reintroduced
#: by the check itself".
_SUN_PATH_BYTES: Final[dict[str, int]] = {
    "linux": 108,
    "darwin": 104,
    "freebsd": 104,
    "openbsd": 104,
    "netbsd": 104,
}

#: What an unrecognised platform gets. The **smaller** of the two figures, because
#: the direction of a wrong guess matters: too small refuses a path that would have
#: worked and says exactly why, while too large passes validation and fails inside
#: ``bind()`` with an errno — the failure this check exists to replace.
_SMALLEST_SUN_PATH: Final[int] = 104


def sun_path_limit() -> int:
    """The running platform's ``sun_path`` budget, terminator included.

    Returns:
        The number of bytes a pathname socket's address may occupy here.
    """
    return _SUN_PATH_BYTES.get(sys.platform, _SMALLEST_SUN_PATH)


def socket_path(data_dir: Path) -> Path:
    """Where the hub listens, given the directory it owns.

    Args:
        data_dir: The absolute, canonical data directory ``Settings`` guarantees.

    Returns:
        ``<data_dir>/hub.sock``.
    """
    return data_dir / SOCKET_FILENAME


def check_socket_path(data_dir: Path) -> None:
    """Refuse a data directory whose path cannot hold the socket (ADR-0084 §1).

    ADR-0083 §5's test applies without strain: restarting unchanged never succeeds,
    and a human must move the data directory — so it is a stay-down deployment
    fault, which :func:`~ai_assistant.service.exits.classify` reaches through
    :class:`~ai_assistant.core.errors.ConfigurationError`.

    **The check is on the encoded byte length** rather than the character count,
    because ``sun_path`` bounds bytes: "a directory named in a non-ASCII script
    spends more of the budget than it looks like it does."

    Args:
        data_dir: The data directory the socket would live in.

    Raises:
        ConfigurationError: If the encoded path plus its terminator exceeds the
            platform's budget. The message names the limit, the encoded length and
            the directory, which is what ADR-0084 §1 asks of it.
    """
    limit = sun_path_limit()
    path = socket_path(data_dir)
    encoded = len(str(path).encode("utf-8")) + 1  # the NUL terminator counts
    if encoded > limit:
        msg = (
            f"the hub's socket path {path} encodes to {encoded} bytes including its "
            f"terminator, over this platform's {limit}-byte sun_path budget, so no socket "
            f"can be bound there; move the data directory somewhere shorter "
            f"(ASSISTANT_DATA_DIR)"
        )
        raise ConfigurationError(msg)
