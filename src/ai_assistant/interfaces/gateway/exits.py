"""What a gateway's exit code means, and how a refusal to start earns one (#3167).

**The hub's table, adopted rather than invented.** ADR-0083 §5 gives the hub three
codes — ``0`` drained, ``1`` come back, ``78`` stay down — and one test for choosing
between the last two: *would restarting, unchanged, ever succeed?* No ADR enumerates
the gateway's exit codes (ADR-0168 calls the command line's "a property of the
adapter, not of the assistant"), so this applies that convention to the gateway's
own faults instead of deciding a second one. The reason is the hub's reason: a
supervisor that cannot tell "come back" from "stay down" restarts a gateway that
refused a setting until someone notices, which is "a crash loop wearing a
diagnosis" (ADR-0083 §5).

**Restated rather than imported.** The hub's constants live in
``ai_assistant.service.exits``, and ``interfaces`` may not import ``service``
(ADR-0084 §6), so the gateway's are written here and a test holds the two equal.

**The verdict is fixed where the refusal is raised, not here.** Every refusal the
gateway raises at start is a :class:`~ai_assistant.core.errors.ConfigurationError`,
and nearly all of them are about a setting or a file that does not change by being
read again — so a ``ConfigurationError`` is a ``78``, exactly as the hub's
:func:`ai_assistant.service.exits.classify` reads one. The few that a restart *can*
get past are raised as :class:`ClearableRefusalError`, a ``ConfigurationError`` still
(so every caller that catches the family is unchanged) that says which side of the
test it is on. Only the place that raises one knows whether the cause can clear,
which is why a classifier reading a message, or an errno three causes down, would
be guessing.
"""

from __future__ import annotations

import errno
from typing import Final

from ai_assistant.core.errors import ConfigurationError

#: A stop was asked for and the gateway stopped. Not restarted (ADR-0083 §5).
EXIT_OK: Final = 0

#: A fault that may clear, so the gateway should come back: restarted (ADR-0083 §5).
EXIT_RESTART: Final = 1

#: **The deployment is wrong.** Restarting unchanged never succeeds, so the
#: supervisor must not restart, and a human acts first (ADR-0083 §5). ``78`` is
#: ``EX_CONFIG`` from ``sysexits.h``, which is what lets a deployment map it with
#: one directive (``RestartPreventExitStatus=78``).
EXIT_DEPLOYMENT: Final = 78

#: The ``errno`` values that mean *the operating system will not let this process do
#: this*, rather than *this failed and might not next time*. The hub's set
#: (``ai_assistant.service.exits``), for the hub's reason: "a directory the process
#: may not write into does not become writable by being opened again" (ADR-0083 §5).
#: On the gateway's path that is a front-end bundle it may not read, or a port below
#: 1024 it may not bind.
#:
#: Left out as deliberately as there: ``EADDRINUSE``, because whatever holds the port
#: is either serving or stopping, as a contended hub lock is (ADR-0083 §1);
#: ``EADDRNOTAVAIL``, ``EMFILE``, ``ENFILE`` and ``ENOSPC``, because some of those
#: clear; and every errno nobody listed, by §5's tie-break.
_STAY_DOWN_ERRNOS: Final = frozenset(
    {
        errno.EACCES,  # permission denied
        errno.EPERM,  # operation not permitted
        errno.EROFS,  # read-only filesystem
        errno.ENOTDIR,  # a path component is not a directory
        errno.EISDIR,  # a directory occupies a file's path
    }
)

#: How far the cause chain is walked before giving up: a guard against a cycle a
#: hand-built ``__cause__`` could create, not a limit anyone should reach.
_MAX_CAUSE_DEPTH: Final = 32


class ClearableRefusalError(ConfigurationError):
    """A refusal to start that restarting, unchanged, may get past: exit ``1``.

    Still a :class:`~ai_assistant.core.errors.ConfigurationError`, so it renders
    and is caught exactly as every other refusal at start is. What it adds is the
    answer to ADR-0083 §5's question, given by the one place that knows it: "if yes
    — even eventually — it is ``1``", and "where a new fault does not obviously
    answer the question, the answer is ``1``: a spurious restart is recoverable and a
    spurious ``78`` is an outage".
    """


def stays_down(exc: OSError) -> bool:
    """Whether the operating system refused in a way no restart changes.

    Args:
        exc: What a start raised.

    Returns:
        ``True`` exactly where its errno is one of :data:`_STAY_DOWN_ERRNOS`.
    """
    return exc.errno in _STAY_DOWN_ERRNOS


def exit_code(exc: BaseException) -> int:
    """The gateway's exit code for a fault that ended it (ADR-0083 §5's test).

    The outermost exception and its explicit ``raise ... from`` chain are read,
    outermost first, and the first that answers decides: a
    :class:`ClearableRefusalError` is :data:`EXIT_RESTART`, any other
    :class:`~ai_assistant.core.errors.ConfigurationError` is
    :data:`EXIT_DEPLOYMENT`. **Only ``__cause__`` is followed, never
    ``__context__``**, for the hub's reason: a cause is an author saying "this
    failure *is* that one, retyped", and a context is whatever happened to be in
    flight.

    **Everything else restarts.** A transport failure, a hub that declined, an
    error nobody classified: §5's tie-break, which is the default the hub takes too.

    Args:
        exc: The fault that ended the gateway.

    Returns:
        :data:`EXIT_DEPLOYMENT` or :data:`EXIT_RESTART`.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and len(seen) < _MAX_CAUSE_DEPTH and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ClearableRefusalError):
            return EXIT_RESTART
        if isinstance(current, ConfigurationError):
            return EXIT_DEPLOYMENT
        current = current.__cause__
    return EXIT_RESTART
