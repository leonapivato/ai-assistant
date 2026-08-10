"""A keyring backend the adapter's tests control, in the shape a real one has.

ADR-0125 §11 requires this lane to run **both shared suites against the adapter**,
"over a backend it controls, so every obligation the suites carry… is proved
against the real wrapper and not only against the fake. The controllable backend is
what makes this possible and the lane owes it."

**It is a backend, not a store.** The subject the suites are handed is the real
:class:`~ai_assistant.secret_store.KeyringSecretStore`; what is doubled here is the
thing underneath it, which is the only place a test can produce the two states §7
and §6 argue about — a keyring that cannot be reached, and one whose own error text
names the value. Doubling the store instead would prove nothing about the wrapper.

**One map per instance, and instances are shared deliberately.** ADR-0125 §11
proves isolation with two subjects over *one* backing, twice, because "two subjects
holding separate maps cannot observe each other's entries however the adapter
composes its coordinates, so the pairing alone proves nothing". One of these
objects behind two stores is that arrangement, and it is also the real deployment:
one OS keyring holds every scope of every installation on the machine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import keyring.errors

from ai_assistant.testing import SecretMethod, disclosure_of

if TYPE_CHECKING:
    from ai_assistant.testing import Disclosure


class ControllableKeyring:
    """An in-memory ``keyring`` backend with the two switches the suites need.

    Attributes:
        available: Whether the backend answers at all. ``False`` models ADR-0125
            §7's one visible state — absent, or present and locked with no unlock
            possible in this session — which the library spells as
            ``NoKeyringError`` and ``KeyringLocked`` respectively.
        last_backend_failure: The text of the disclosing error the last armed
            failure raised, or ``None``. The **negative control** the redaction
            cases need: without it, a double that quietly stopped building a
            disclosing text would make every "the plaintext is absent" assertion
            pass while proving nothing.
    """

    def __init__(self) -> None:
        """Create an empty backend that answers."""
        self.entries: dict[tuple[str, str], str] = {}
        self.available = True
        self.last_backend_failure: str | None = None
        self._armed: dict[SecretMethod, Disclosure] = {}

    def arm(self, method: SecretMethod, disclosure: Disclosure) -> None:
        """Make the next call to ``method`` fail with an error naming the value.

        The text quotes :func:`~ai_assistant.testing.disclosure_of` over the
        plaintext that call is about — the value held for the coordinate on a read
        or a removal, the value it was given on a write — which is exactly the
        backend behaviour ADR-0125 §11 requires the adapter to be proved against.

        Args:
            method: Which of the seam's three methods fails.
            disclosure: Which derivation ADR-0125 §6 forbids the error carries.
        """
        self._armed[method] = disclosure

    # --- the `keyring` backend surface --------------------------------------

    def get_password(self, service_name: str, username: str) -> str | None:
        """Return what is stored at a coordinate, or ``None``."""
        self._answer_or_raise(SecretMethod.GET, self.entries.get((service_name, username)))
        return self.entries.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        """Store a value at a coordinate, replacing whatever was there."""
        self._answer_or_raise(SecretMethod.SET, password)
        self.entries[service_name, username] = password

    def delete_password(self, service_name: str, username: str) -> None:
        """Remove a coordinate, raising ``PasswordDeleteError`` where there is none."""
        self._answer_or_raise(SecretMethod.DELETE, self.entries.get((service_name, username)))
        if self.entries.pop((service_name, username), None) is None:
            msg = "no such entry"
            raise keyring.errors.PasswordDeleteError(msg)

    def _answer_or_raise(self, method: SecretMethod, plaintext: str | None) -> None:
        """Apply the two switches, unavailability first.

        Unavailability is checked before the armed failure because a backend that
        cannot be reached never gets as far as rejecting a value — and because the
        suite drives the two states independently, never together.

        Raises:
            KeyringLocked: If the backend has been made unavailable.
            KeyringError: If ``method`` was armed. Its own text carries the
                derivation, which is what the adapter must not pass on.
        """
        if not self.available:
            msg = "the keyring is present and locked, and no unlock is possible in this session"
            raise keyring.errors.KeyringLocked(msg)
        disclosure = self._armed.pop(method, None)
        if disclosure is None:
            return
        self.last_backend_failure = (
            None
            if plaintext is None
            else f"keyring: {method.value} rejected {disclosure_of(disclosure, plaintext)}"
        )
        raise keyring.errors.KeyringError(self.last_backend_failure or "keyring: refused")
