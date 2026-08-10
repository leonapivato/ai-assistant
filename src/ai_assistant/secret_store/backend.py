"""Which backing the keyring seam will use, and which it refuses to use.

ADR-0125 §7 is unusually categorical about this one thing, so the selection is a
module of its own rather than three lines inside the store:

> **Normative.** An implementation may not fall back. When the keyring is
> unavailable it raises; it does not substitute a file, an environment variable, an
> in-memory map, or any backend that stores a value without the operating system's
> own access control on it.

**The hazard is concrete rather than theoretical**, and §7 names it: "cross-platform
keyring stacks ship alternative backends that store to a plaintext or
weakly-obscured file and can be selected by configuration or by what happens to be
installed, so 'it worked on the headless box' is exactly how this arrives." The
`keyring` library's own chain will happily select such a backend when nothing
better is present, which is why this module does not delegate the choice to it.

**The rule is an allow-list and that is the fail-closed direction.** A deny-list of
the plaintext backends shipped today would admit tomorrow's, and admit any backend
a ``keyringrc.cfg`` names. So a backing is used only when the module it comes from
is one this project has looked at and found to be the operating system's own
credential service — which is the custody ADR-0124 §6 traded for its exemption from
ADR-0004 §7's gate, and an unprotected backend would make that exemption unearned.

**Nothing here is asked at construction** (ADR-0125 §7): the store calls
:func:`select_backend` on each operation, so a deployment with no keyring and no
consumer needing one starts normally, and a keyring unlocked after the process
started begins working without a restart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol, cast, runtime_checkable

import keyring
import keyring.errors

from ai_assistant.core.errors import SecretStoreUnavailableError

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The backend modules whose storage the operating system itself protects.
#:
#: Each is a platform's own credential service reached through its own API, so the
#: access control on a stored value is the OS's rather than a file mode this
#: project chose — which is the second of the three replacements ADR-0124 §6 traded
#: for its exemption from ADR-0004 §7's gate.
#:
#: **A module absent from this set is refused, not ranked lower.** That includes
#: ``keyring.backends.fail`` (the placeholder for "nothing usable"),
#: ``keyring.backends.null`` (which discards what it is given), and the whole
#: ``keyrings.alt`` family, whose members store to a plaintext or
#: passphrase-obscured file. It also includes any backend this project has not
#: seen, which is the point of writing the rule this way round.
PROTECTED_BACKEND_MODULES: Final[frozenset[str]] = frozenset(
    {
        # freedesktop.org Secret Service over D-Bus — GNOME Keyring, KeePassXC and
        # anything else exposing that interface. Two bindings, both accepted.
        "keyring.backends.SecretService",
        "keyring.backends.libsecret",
        # KDE's Wallet, over the same session bus.
        "keyring.backends.kwallet",
        # The macOS Keychain, through Security.framework.
        "keyring.backends.macOS",
        # The Windows Credential Vault, through wincred.
        "keyring.backends.Windows",
    }
)


@runtime_checkable
class KeyringBackend(Protocol):
    """The three calls this seam makes of a keyring, as `keyring` spells them.

    Declared here rather than taken from the library so that the store can be
    driven against a backing a test controls — which ADR-0125 §11 requires of this
    lane in as many words, since every obligation a shared suite carries can be
    satisfied by the canonical fake, and the properties §7 argues hardest about
    live in the adapter.

    The methods are **synchronous**, because the library's are: a backend call is a
    round trip to an operating-system service and, on a locked store, one whose
    duration is bounded by the owner typing a passphrase. The store runs them in a
    worker thread behind its own ``async`` methods (ADR-0125 §1).
    """

    def get_password(self, service_name: str, username: str) -> str | None:
        """Return the value stored at a coordinate, or ``None`` if there is none."""

    def set_password(self, service_name: str, username: str, password: str) -> None:
        """Store a value at a coordinate, replacing whatever was there."""

    def delete_password(self, service_name: str, username: str) -> None:
        """Remove the entry at a coordinate, raising if there is none."""


def _leaves(backing: object) -> Iterator[object]:
    """Every backend a selection actually resolves to, chains expanded.

    ``keyring`` can hand back a chaining backend whose own ``backends`` attribute
    holds the real ones in priority order. Asking only about the object returned
    would then be asking about a wrapper, and a chain containing a plaintext
    backend would pass a check written against the wrapper's own module.

    Args:
        backing: Whatever the selection produced.

    Yields:
        Each non-chaining backend it would reach, outermost priority first.
    """
    chained = getattr(backing, "backends", None)
    if chained is None:
        yield backing
        return
    for one in chained:
        yield from _leaves(one)


def _is_protected(backing: object) -> bool:
    """Whether ``backing`` comes from a module in :data:`PROTECTED_BACKEND_MODULES`.

    The submodule test is what makes the set list packages rather than classes: a
    platform binding may declare its backend in a submodule of the package named
    here, and naming the package is the durable half of the fact.

    Args:
        backing: One non-chaining backend.

    Returns:
        Whether this seam may store a secret in it.
    """
    module = type(backing).__module__
    return any(
        module == allowed or module.startswith(f"{allowed}.")
        for allowed in PROTECTED_BACKEND_MODULES
    )


def _describe(backing: object) -> str:
    """Name one backend the way an operator can act on (ADR-0125 §7)."""
    return f"{type(backing).__module__}.{type(backing).__qualname__}"


def select_backend() -> KeyringBackend:
    """The keyring this machine offers, or a refusal naming what was found.

    Returns:
        The highest-priority backing whose storage the operating system protects.
        Chains are already priority-ordered by the library, so the first protected
        leaf is the one that would have been used.

    Raises:
        SecretStoreUnavailableError: If no protected backing is present. **Never a
            fallback** (ADR-0125 §7): the remedy for a headless box is a keyring the
            operator installs and unlocks, and the fault stays legible until they
            do, which is the posture ADR-0084 §9 takes for a hub that is down. The
            message states the condition "in terms the operator can act on — which
            backend was looked for and what was found — and never in terms of a
            value".
    """
    try:
        selected = keyring.get_keyring()
    except Exception as exc:
        # **Every failure, not only the library's own error type.** Selecting a
        # backend runs a priority check inside whichever backend was named, and that
        # check reports an unreachable service by raising whatever *it* uses:
        # `PYTHON_KEYRING_BACKEND=keyring.backends.SecretService.Keyring` on a
        # machine with no D-Bus raises a bare ``RuntimeError``, which is not a
        # ``KeyringError`` — and that is not an exotic case, it is precisely the
        # configured headless deployment ADR-0125 §7 spends its longest argument on.
        # An escape there is a traceback where §7 promises a legible refusal.
        # ``Exception`` and not ``BaseException``, so a cancellation still
        # propagates (ADR-0060).
        found = f"a {type(exc).__name__} while resolving one"
    else:
        leaves = tuple(_leaves(selected))
        for leaf in leaves:
            if _is_protected(leaf):
                # ``cast`` rather than an ``isinstance`` gate: the Protocol is
                # structural and every backend in the allow-list satisfies it, so a
                # runtime check here would only ask a question the library's own
                # base class has already answered.
                return cast("KeyringBackend", leaf)
        found = ", ".join(_describe(leaf) for leaf in leaves) or "nothing"
    # Raised outside the ``except`` clause so that no backend exception becomes this
    # one's ``__context__``. That is not tidiness: ADR-0125 §6 binds every rendering
    # of an exception this seam raises, and a chained cause is rendered in the
    # traceback a reader actually sees.
    msg = (
        f"no keyring backend with the operating system's own access control is available "
        f"on this machine. Looked for one of {sorted(PROTECTED_BACKEND_MODULES)}, and "
        f"'keyring' offered {found}. This seam never falls back to a file, an environment "
        f"variable or an in-memory map (ADR-0125 §7): install and unlock your platform's "
        f"credential service, or on a headless machine run one and unlock it for this "
        f"session"
    )
    raise SecretStoreUnavailableError(msg)
