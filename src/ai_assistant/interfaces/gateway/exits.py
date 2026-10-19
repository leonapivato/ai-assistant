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

**Two things decide a refusal's code, and both are a test rather than a list of
refusals** — §5's own instruction, "because a list is what gets out of date the
first time a fault arrives by a route nobody enumerated":

1. **What the refusal is.** Every refusal the gateway raises at start is a
   :class:`~ai_assistant.core.errors.ConfigurationError`, and a
   ``ConfigurationError`` is a ``78``, as the hub's
   :func:`ai_assistant.service.exits.classify` reads one. A refusal whose author
   knows a restart can get past it is raised as :class:`ClearableRefusalError` — a
   ``ConfigurationError`` still, so every caller catching the family is unchanged —
   and is a ``1``: a certificate the clock has not reached, an overlay agent that
   would not answer, a port something else holds.
2. **What it retypes.** A ``ConfigurationError`` raised *from* an ``OSError`` says
   "the operating system refused while this was being read", and whether that
   clears is the errno's to say, not the refusal's. A path that names nothing, a
   permission, an address this machine does not hold: ``78``. Descriptors
   exhausted, an I/O error, anything else: ``1``. Without this, a certificate read
   that met ``ENFILE`` would leave a correctly configured gateway down for good —
   and the refusals that retype an ``OSError`` are spread across ``tls.py``,
   ``server.py`` and ``ai_assistant.wire.overlay``'s custody checks, which is
   exactly the route nobody enumerated.
"""

from __future__ import annotations

import errno
import ssl
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
#: ``EMFILE``, ``ENFILE``, ``ENOSPC`` and ``EIO``, because those clear; and every
#: errno nobody listed, by §5's tie-break. ``ENOENT`` and ``EADDRNOTAVAIL`` are left
#: out *here* because a raw one is not about anything configured — an agent socket
#: not there yet, an address that went away under a bind — see
#: :data:`_CONFIGURED_ERRNOS` for where they are.
_STAY_DOWN_ERRNOS: Final = frozenset(
    {
        errno.EACCES,  # permission denied
        errno.EPERM,  # operation not permitted
        errno.EROFS,  # read-only filesystem
        errno.ENOTDIR,  # a path component is not a directory
        errno.EISDIR,  # a directory occupies a file's path
    }
)

#: The ``errno`` values that, under a refusal about something **configured**, mean
#: the configuration is what is wrong: :data:`_STAY_DOWN_ERRNOS`, and a configured
#: path that names nothing (``ENOENT``, ``ELOOP``, ``ENAMETOOLONG``) or a configured
#: address no interface here holds (``EADDRNOTAVAIL``). A file that appears later is
#: one a person or their tooling put there, which is the human act §5's ``78``
#: waits for.
_CONFIGURED_ERRNOS: Final = _STAY_DOWN_ERRNOS | frozenset(
    {errno.ENOENT, errno.ELOOP, errno.ENAMETOOLONG, errno.EADDRNOTAVAIL}
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
    """Whether a raw operating-system refusal is one no restart changes.

    Args:
        exc: What a start raised, not yet retyped by anything that knew what it was
            reading.

    Returns:
        ``True`` exactly where its errno is one of :data:`_STAY_DOWN_ERRNOS`.
    """
    return exc.errno in _STAY_DOWN_ERRNOS


def _retypes_a_fault_that_clears(refusal: ConfigurationError) -> bool:
    """Whether ``refusal`` retypes an operating-system fault a restart may clear.

    ``ssl.SSLError`` is an ``OSError`` whose ``errno`` is the TLS library's own code
    rather than the kernel's, and it says the material is unusable — a key that is
    not the certificate's — so it is the refusal's verdict that stands, not an errno.

    Args:
        refusal: A refusal at start.

    Returns:
        ``True`` where its direct cause is such a fault.
    """
    cause = refusal.__cause__
    if not isinstance(cause, OSError) or isinstance(cause, ssl.SSLError):
        return False
    return cause.errno not in _CONFIGURED_ERRNOS


def exit_code(exc: BaseException) -> int:
    """The gateway's exit code for a fault that ended it (ADR-0083 §5's test).

    The outermost exception and its explicit ``raise ... from`` chain are read,
    outermost first, and the first refusal decides: a
    :class:`ClearableRefusalError` is :data:`EXIT_RESTART`; any other
    :class:`~ai_assistant.core.errors.ConfigurationError` is
    :data:`EXIT_DEPLOYMENT`, unless it retypes an operating-system fault that may
    clear (the module's second rule), which is :data:`EXIT_RESTART`. **Only
    ``__cause__`` is followed, never ``__context__``**, for the hub's reason: a
    cause is an author saying "this failure *is* that one, retyped", and a context
    is whatever happened to be in flight.

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
            if _retypes_a_fault_that_clears(current):
                return EXIT_RESTART
            return EXIT_DEPLOYMENT
        current = current.__cause__
    return EXIT_RESTART
