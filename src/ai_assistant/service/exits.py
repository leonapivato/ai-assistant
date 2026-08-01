"""What a hub exit code means, and how a startup failure earns one (ADR-0083 §5).

The distinction the table draws is the whole point of it: **a crash loop is a
process that never explains itself, and a fatal refusal a supervisor keeps
restarting is a crash loop wearing a diagnosis.** So the codes separate "come
back" from "stay down", and this module is the one place a failure is turned into
one of them.
"""

from __future__ import annotations

import errno
from typing import Final

from ai_assistant.core.errors import ConfigurationError, IncompatibleStateError

#: A stop was requested and the drain completed. The supervisor should not
#: restart (ADR-0083 §3's S2).
EXIT_OK: Final = 0

#: An unexpected fault, **or a contended instance lock**. The process should come
#: back, so the supervisor restarts it (ADR-0083 §3's S4).
#:
#: Lock contention is deliberately here and not with the deployment faults, and
#: ADR-0083 §1 writes the reasoning down because the appealing answer is wrong. A
#: held lock always means a live holder, and a live holder is either **serving** —
#: in which case the deployment is up and the loser's restart loop is harmless
#: noise a supervisor backs off from — or **draining**, in which case a later
#: attempt succeeds. Treating contention as a stay-down code would make the second
#: case fatal: phase B of shutdown is unbounded, so a drain can outlast any retry
#: window, and refusing to restart there leaves **no** hub running after the
#: outgoing one exits cleanly, with nothing wrong for anyone to fix.
EXIT_RESTART: Final = 1

#: **The deployment is wrong.** This build cannot serve this environment or this
#: state, and restarting changes nothing until a human acts, so the supervisor
#: must not restart (ADR-0083 §3's S3, D1).
#:
#: ``78`` is ``EX_CONFIG`` from ``sysexits.h`` — an existing convention rather than
#: an invented number, which is what lets a reference deployment map it with one
#: directive (``RestartPreventExitStatus=78``).
EXIT_DEPLOYMENT: Final = 78

#: The ``errno`` values that mean *this filesystem will not let this process do
#: this*, as opposed to *this operation failed and might not next time*.
#:
#: ADR-0083 §3 step 3 requires a filesystem access fault to be a stay-down exit
#: **wherever in startup it surfaces**, "because step 2's check is necessary and
#: not sufficient: ``mkdir(exist_ok=True)`` succeeds on an existing directory the
#: process may not write into, and a database file can be unreadable inside a
#: writable directory". §5 gives the reason a restart is the wrong answer: "a
#: directory the process may not write into does not become writable by being
#: opened again, and mapping it to ``1`` buys an infinite restart loop against an
#: unchanging ``EACCES``".
#:
#: What is **not** here is as deliberate. ``ENOSPC`` and ``EMFILE`` are omitted
#: because §5 puts "an exhausted disk" on the restart side — some of those clear.
#: ``ENOENT`` is omitted because startup creates what is missing.
_STAY_DOWN_ERRNOS: Final = frozenset(
    {
        errno.EACCES,  # permission denied
        errno.EPERM,  # operation not permitted
        errno.EROFS,  # read-only filesystem
        errno.ENOTDIR,  # a path component is not a directory
        errno.EISDIR,  # a directory occupies a file's path
    }
)

#: How far the cause chain is walked before giving up. A guard against a cycle a
#: hand-built ``__cause__`` could create, not a limit anyone should reach.
_MAX_CAUSE_DEPTH: Final = 32


def _causes(exc: BaseException) -> list[BaseException]:
    """The exception and its explicit ``raise ... from`` chain, outermost first.

    **Only ``__cause__`` is followed, never ``__context__``.** A cause is an author
    saying "this failure *is* that one, retyped"; a context is merely whatever
    happened to be in flight, and following it would let an unrelated error caught
    and handled somewhere inside a store decide the hub's exit code.

    Args:
        exc: The exception to walk from.

    Returns:
        The chain, starting with ``exc`` itself. Cycles and runaway depth are cut.
    """
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and len(chain) < _MAX_CAUSE_DEPTH:
        if id(current) in seen:
            break
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__
    return chain


def classify(exc: BaseException) -> tuple[int, str]:
    """Decide a startup failure's exit code and the action it asks of a human.

    **The boundary is a test, not a list** (ADR-0083 §5), because a list is what
    gets out of date the first time a fault arrives by a route nobody enumerated.
    The test is one question: *would restarting, unchanged, ever succeed?* If no,
    it is :data:`EXIT_DEPLOYMENT` and a human must act. If yes — even eventually —
    it is :data:`EXIT_RESTART`.

    The three branches below are that test applied, not a taxonomy:

    * :class:`~ai_assistant.core.errors.IncompatibleStateError` — state this build
      cannot serve correctly (ADR-0083 §6). It carries its own operator action,
      which is why it is checked first and why nothing here has to invent one.
    * :class:`~ai_assistant.core.errors.ConfigurationError` — every startup
      misconfiguration already arrives as this class: settings that will not load,
      a model spec naming an uninstalled vendor, a vendor with no credential
      (#530), an unbuildable embedder, a data directory that cannot be prepared.
      None of them clears itself.
    * A filesystem access fault anywhere in the cause chain
      (:data:`_STAY_DOWN_ERRNOS`).

    **Everything else restarts**, and that default is the decision §5 states:
    "where a new fault does not obviously answer the question, the answer is
    ``1``: a spurious restart is recoverable and a spurious ``78`` is an outage."
    A store that fails to open on a corrupt page or an exhausted disk lands here,
    which is exactly where §5 puts it.

    Args:
        exc: The exception that ended startup.

    Returns:
        The exit code, and the operator action to print alongside the cause. The
        action is empty for :data:`EXIT_RESTART`: nothing is being asked of a
        human, so printing an instruction would invent one.
    """
    for cause in _causes(exc):
        if isinstance(cause, IncompatibleStateError):
            return EXIT_DEPLOYMENT, cause.operator_action
        if isinstance(cause, ConfigurationError):
            return EXIT_DEPLOYMENT, "correct the configuration, then start the hub again"
        if isinstance(cause, OSError) and cause.errno in _STAY_DOWN_ERRNOS:
            target = cause.filename if cause.filename is not None else "the data directory"
            return (
                EXIT_DEPLOYMENT,
                f"make {target} readable and writable by the user the hub runs as, "
                f"then start the hub again",
            )
    return EXIT_RESTART, ""
