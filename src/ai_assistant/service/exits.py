"""What a hub exit code means, and how a startup failure earns one (ADR-0083 §5).

The distinction the table draws is the whole point of it: **a crash loop is a
process that never explains itself, and a fatal refusal a supervisor keeps
restarting is a crash loop wearing a diagnosis.** So the codes separate "come
back" from "stay down", and this module is the one place a failure is turned into
one of them.

**Two things decide what a** ``ConfigurationError`` **earns, and both are a test
rather than a list of refusals** (#3171, the hub's half of what #3167 settled for
the gateway in ``ai_assistant.interfaces.gateway.exits``):

1. **What the refusal is.** A ``ConfigurationError`` is a ``78``. A refusal whose
   author knows a restart can get past it is raised as :class:`ClearableRefusalError`
   — a ``ConfigurationError`` still, so every caller catching the family is
   unchanged — and is a ``1``: an overlay agent that would not answer at start, which
   is also an agent that timed out or has not come up yet at boot. **The mark lowers
   only the refusal's own verdict**: the chain beneath it is still read, so a
   permission fault under it stays down, as §5 requires of one "wherever in startup
   it surfaces".
2. **What it retypes.** A ``ConfigurationError`` raised *from* an ``OSError`` says
   "the operating system refused while this was being read", and whether that clears
   is the errno's to say, not the refusal's. A path that names nothing, a
   permission, an address this machine does not hold: ``78``. Descriptors
   exhausted, an I/O error, any other errno: ``1``. An ``OSError`` with **no**
   errno — a shared library the loader cannot open — is no kernel verdict at all,
   so the refusal's own ``78`` stands. That is narrower than the gateway's reading,
   on purpose: the hub's start wraps an unloadable on-device runtime this way, and
   reinstalling it is a human act.
"""

from __future__ import annotations

import errno
import ssl
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

#: The ``errno`` values that, under a refusal about something **configured**, mean
#: the configuration is what is wrong: :data:`_STAY_DOWN_ERRNOS`, and a configured
#: path that names nothing (``ENOENT``, ``ELOOP``, ``ENAMETOOLONG``) or a configured
#: address no interface here holds (``EADDRNOTAVAIL``). A file that appears later is
#: one a person or their tooling put there, which is the human act §5's ``78`` waits
#: for. The gateway's set, for the gateway's reason (#3167), so the two read one
#: refusal the same way.
#:
#: Read **only** for a ``ConfigurationError`` whose direct cause is the ``OSError``.
#: A raw ``ENOENT`` stays a ``1``, because startup creates what is missing; what
#: makes it a ``78`` here is that something configured named it.
_CONFIGURED_ERRNOS: Final = _STAY_DOWN_ERRNOS | frozenset(
    {errno.ENOENT, errno.ELOOP, errno.ENAMETOOLONG, errno.EADDRNOTAVAIL}
)

#: How far the cause chain is walked before giving up. A guard against a cycle a
#: hand-built ``__cause__`` could create, not a limit anyone should reach.
_MAX_CAUSE_DEPTH: Final = 32


class ClearableRefusalError(ConfigurationError):
    """A refusal to start that restarting, unchanged, may get past: exit ``1``.

    Still a :class:`~ai_assistant.core.errors.ConfigurationError`, so it renders and
    is caught exactly as every other refusal at start is. What it adds is the answer
    to ADR-0083 §5's question, given by the one place that knows it: "if yes — even
    eventually — it is ``1``", and "where a new fault does not obviously answer the
    question, the answer is ``1``: a spurious restart is recoverable and a spurious
    ``78`` is an outage".
    """


def _retypes_a_fault_that_clears(refusal: ConfigurationError) -> bool:
    """Whether ``refusal`` retypes an operating-system fault a restart may clear.

    ``ssl.SSLError`` is an ``OSError`` whose ``errno`` is the TLS library's own code
    rather than the kernel's, and it says the material is unusable, so it is the
    refusal's verdict that stands, not an errno. The hub reads no TLS material at
    start today; the exception is kept so this reads a TLS refusal as the
    gateway's ``exit_code`` does.

    An ``OSError`` with no errno is not a kernel verdict either — ``ctypes`` and the
    import machinery raise one for a shared library that will not load, which no
    restart repairs — so it too leaves the refusal's verdict standing.

    Args:
        refusal: A refusal at start.

    Returns:
        ``True`` where its direct cause is such a fault.
    """
    cause = refusal.__cause__
    if not isinstance(cause, OSError) or isinstance(cause, ssl.SSLError):
        return False
    return cause.errno is not None and cause.errno not in _CONFIGURED_ERRNOS


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

    The branches below are that test applied, not a taxonomy. The chain is read
    outermost first, and the first exception a branch names decides:

    * :class:`~ai_assistant.core.errors.IncompatibleStateError` — state this build
      cannot serve correctly (ADR-0083 §6). It carries its own operator action,
      which is why it is checked first and why nothing here has to invent one.
    * :class:`ClearableRefusalError` — a refusal its author knows a restart can get
      past, such as an overlay agent that would not answer at start (#3171). It
      decides nothing itself: the walk goes on beneath it, and where nothing below
      stays down it ends at :data:`EXIT_RESTART`. So an agent socket that refused
      with ``EACCES`` is still a ``78``, while one that is absent or timed out is a
      ``1``.
    * :class:`~ai_assistant.core.errors.ConfigurationError` — every startup
      misconfiguration already arrives as this class: settings that will not load,
      a model spec naming an uninstalled vendor, a vendor with no credential
      (#530), an unbuildable embedder, a data directory that cannot be prepared.
      None of them clears itself — **unless it retypes an operating-system fault
      that does**: one raised directly from an ``OSError`` whose errno is outside
      :data:`_CONFIGURED_ERRNOS` (descriptors exhausted, an I/O error) is
      :data:`EXIT_RESTART`, because the errno, not the wrapper, says whether the
      fault clears (#3171).
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
        if isinstance(cause, ClearableRefusalError):
            continue
        if isinstance(cause, ConfigurationError):
            if _retypes_a_fault_that_clears(cause):
                return EXIT_RESTART, ""
            return EXIT_DEPLOYMENT, "correct the configuration, then start the hub again"
        if isinstance(cause, OSError) and cause.errno in _STAY_DOWN_ERRNOS:
            target = cause.filename if cause.filename is not None else "the data directory"
            return (
                EXIT_DEPLOYMENT,
                f"make {target} readable and writable by the user the hub runs as, "
                f"then start the hub again",
            )
    return EXIT_RESTART, ""
