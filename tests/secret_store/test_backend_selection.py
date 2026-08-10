"""The two obligations no shared suite can express (ADR-0125 §11).

> **Normative.** Two further obligations are that lane's alone, because no suite
> running against any subject can express them: that a backend selection which
> finds nothing usable **raises rather than falling back** (§7), and that no backend
> storing a value without the operating system's own access control is ever
> selected.

Both are about which backend gets *selected*, and "a subject handed to a suite has
already been constructed" — so they are asserted here, against
:func:`~ai_assistant.secret_store.select_backend` itself. ADR-0125 §11 says why
they cannot be left to the suite: "Every obligation the shared suite carries can be
satisfied by the canonical fake, which has no backend to select and cannot fall
back — so a triad that goes green proves nothing about the property §7 spends its
longest argument on."

**The library's own objects are used where the module name is the fact under
test.** ``keyring.backends.fail.Keyring`` is the real placeholder for "nothing
usable", ``keyring.backends.null.Keyring`` is the real backend that discards what
it is given, and ``keyring.backends.SecretService.Keyring`` is a real protected one
— constructing any of them touches no D-Bus. A stand-in class would have this
module's own ``__module__`` and would therefore be testing a name this test chose.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import keyring
import keyring.backends.fail
import keyring.backends.null
import keyring.backends.SecretService
import keyring.errors
import pytest

from ai_assistant.core.errors import SecretStoreUnavailableError
from ai_assistant.secret_store import PROTECTED_BACKEND_MODULES, select_backend

if TYPE_CHECKING:
    from collections.abc import Sequence


class _Chain:
    """A chaining backend, in the shape `keyring`'s own has: priority-ordered leaves."""

    def __init__(self, backends: Sequence[object]) -> None:
        self.backends = list(backends)


class _PlaintextFile:
    """A backend that stores to a file this project has never looked at.

    Stands for the whole ``keyrings.alt`` family, which is not installed here and
    must not become a test dependency. What matters is that its module is one
    :data:`PROTECTED_BACKEND_MODULES` does not name — which is the property the
    allow-list is written to decide, and the reason it is an allow-list.
    """

    def get_password(self, service_name: str, username: str) -> str | None:
        raise NotImplementedError

    def set_password(self, service_name: str, username: str, password: str) -> None:
        raise NotImplementedError

    def delete_password(self, service_name: str, username: str) -> None:
        raise NotImplementedError


def _offer(monkeypatch: pytest.MonkeyPatch, backing: object) -> None:
    """Make ``keyring.get_keyring()`` return ``backing``."""
    monkeypatch.setattr(keyring, "get_keyring", lambda: backing)


def test_a_protected_backend_is_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ordinary case: a platform credential service is used as it is."""
    protected = keyring.backends.SecretService.Keyring()
    _offer(monkeypatch, protected)

    assert select_backend() is protected


def test_nothing_usable_raises_rather_than_falling_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0125 §7's clause, against the library's own "nothing usable" placeholder.

    The remedy for a headless box "is a keyring the operator installs and unlocks,
    and the fault is legible until they do — which is the posture ADR-0084 §9 takes
    for a hub that is down". This is the case where a fallback would be most
    tempting and where it would remove the operating-system custody ADR-0124 §6
    traded for its exemption from ADR-0004 §7's gate.
    """
    _offer(monkeypatch, keyring.backends.fail.Keyring())

    with pytest.raises(SecretStoreUnavailableError) as raised:
        select_backend()

    assert "keyring.backends.fail" in str(raised.value), "the message must name what was found"
    assert "never falls back" in str(raised.value)


def test_an_unprotected_backend_is_never_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A backend the operating system does not protect is refused, not ranked lower.

    The allow-list is what makes this hold for a backend nobody has seen: a
    deny-list of the plaintext backends shipped today would admit tomorrow's, and
    admit whatever a ``keyringrc.cfg`` names.
    """
    _offer(monkeypatch, _PlaintextFile())

    with pytest.raises(SecretStoreUnavailableError):
        select_backend()


def test_a_backend_that_discards_what_it_is_given_is_never_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The null backend is the worst fallback available and is refused like the rest.

    It satisfies every method signature and stores nothing, so a system that
    selected it would report a successful enrolment and then find no credential at
    the first connect — an "unenrolled" device the owner enrolled twice.
    """
    _offer(monkeypatch, keyring.backends.null.Keyring())

    with pytest.raises(SecretStoreUnavailableError):
        select_backend()


def test_a_chain_is_expanded_and_its_protected_member_is_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chain is not a backend, and asking about the wrapper asks the wrong question.

    ``keyring`` can hand back a chaining backend, and its module is not any leaf's.
    An implementation that tested the object it was given would refuse every chain,
    or — worse, if the chain's own module were ever allow-listed — accept whatever
    the chain contains.
    """
    protected = keyring.backends.SecretService.Keyring()
    _offer(monkeypatch, _Chain([_PlaintextFile(), protected]))

    assert select_backend() is protected


def test_a_chain_of_unprotected_backends_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """And expanding a chain is not a way in: every leaf is held to the same rule."""
    _offer(monkeypatch, _Chain([_PlaintextFile(), keyring.backends.null.Keyring()]))

    with pytest.raises(SecretStoreUnavailableError):
        select_backend()


def test_an_unprotected_backend_ahead_of_a_protected_one_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Priority does not override the rule, and the direction matters.

    A plaintext backend that happens to sort first is exactly how "it worked on the
    headless box" arrives (ADR-0125 §7). It is passed over rather than allowed to
    win, and the protected one behind it is used.
    """
    protected = keyring.backends.SecretService.Keyring()
    _offer(monkeypatch, _Chain([keyring.backends.null.Keyring(), protected]))

    assert select_backend() is protected


def test_an_empty_chain_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing to select is the same answer as nothing usable, not an empty success."""
    _offer(monkeypatch, _Chain([]))

    with pytest.raises(SecretStoreUnavailableError) as raised:
        select_backend()

    assert "nothing" in str(raised.value)


def test_a_library_that_cannot_resolve_one_at_all_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``get_keyring`` raising is a refusal, not a crash out of the seam.

    ADR-0125 §7 requires the condition to be stated "in terms the operator can act
    on", and an exception from inside the library is not that.
    """

    def refuse() -> Any:
        msg = "no backend"
        raise keyring.errors.NoKeyringError(msg)

    monkeypatch.setattr(keyring, "get_keyring", refuse)

    with pytest.raises(SecretStoreUnavailableError) as raised:
        select_backend()

    assert "could not resolve one at all" in str(raised.value)
    assert raised.value.__context__ is None, "a backend error must not be chained (§6)"


def test_the_allow_list_names_packages_that_exist() -> None:
    """Each entry is a real `keyring` backend package, not a name someone guessed.

    Only the two this platform can import are checked, because the macOS and
    Windows modules import platform APIs that do not exist here. What the case
    protects against is a typo in the set: a misspelt module admits nothing, so the
    seam would refuse a perfectly good keyring and the fault would look like a
    missing backend.
    """
    importable = {"keyring.backends.SecretService", "keyring.backends.libsecret"}
    assert importable <= PROTECTED_BACKEND_MODULES
    for module in sorted(importable):
        __import__(module)


def test_the_two_placeholders_are_absent_from_the_allow_list() -> None:
    """Stated as well as exercised, because the set is the whole of the rule."""
    assert "keyring.backends.fail" not in PROTECTED_BACKEND_MODULES
    assert "keyring.backends.null" not in PROTECTED_BACKEND_MODULES
    assert not any(name.startswith("keyrings.alt") for name in PROTECTED_BACKEND_MODULES)
