"""The canonical fake against both shared conformance suites (ADR-0151, ADR-0153).

Two bindings over **one** class, which is the arrangement ADR-0153 §2 rules for the
production implementation and which the fake mirrors: one object satisfies the wide
face and the narrow one, with a single ``connected`` serving both. The hooks are
supplied once, on a mixin, for the same reason
``tests/core/test_fake_secrets.py``'s are.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from connection_provisioner_contract import ConnectionProvisionerContract, credential
from connection_purger_contract import ConnectionPurgerContract

from ai_assistant.testing import Disclosure, FakeConnectionProvisioner, SecretMethod

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ConnectionProvisioner, ConnectionPurger
    from ai_assistant.testing.cancellation import SuspendedCall


def _fake(subject: object) -> FakeConnectionProvisioner:
    """Narrow a suite's subject to the fake the hooks below reach into.

    The suites declare their hooks over the Protocol, because that is what the
    obligation is about; a binding still has to get at the switches its own subject
    carries, and those are not on any seam a consumer depends on.
    """
    assert isinstance(subject, FakeConnectionProvisioner)
    return subject


class FakeConnectionHooks:
    """The hooks both suites take, supplied once for the one canonical fake."""

    def keyring_entries(self, provisioner: object) -> int:
        """How many credentials the fake's keyring holds."""
        return len(_fake(provisioner).secrets.backing)

    def fail_next(self, provisioner: object, method: SecretMethod) -> None:
        """Arm the fake's keyring to fail its next call to ``method``."""
        _fake(provisioner).secrets.fail(method, Disclosure.VERBATIM)

    def repeat_next_reference(self, provisioner: object) -> None:
        """Script the fake's reference factory to repeat its last value."""
        _fake(provisioner).repeat_next_reference()

    def entry_count(self, purger: object) -> int:
        """How many entries the fake's append-only log holds."""
        return len(_fake(purger).entries)

    def fail_next_deletion(self, purger: object) -> None:
        """Arm the fake's keyring to fail its next deletion."""
        _fake(purger).secrets.fail(SecretMethod.DELETE, Disclosure.VERBATIM)

    def keyring_becomes_unreachable(self, purger: object) -> None:
        """Put the fake's keyring into ADR-0125 §7's unavailable state."""
        _fake(purger).secrets.become_unavailable()

    def mint_an_unusable_reference(self, provisioner: object) -> None:
        """Script the fake's factory to mint a reference past ADR-0151 §11's bound."""
        _fake(provisioner).mint_an_unusable_reference()

    def suspend_next_credential_write(self, provisioner: object) -> SuspendedCall:
        """Hold the fake's next credential write open."""
        return _fake(provisioner).suspend_next_credential_write()

    def suspend_next_deletion(self, purger: object) -> SuspendedCall:
        """Hold the fake's next credential deletion open."""
        return _fake(purger).suspend_next_deletion()

    async def connect(self, purger: object, identity: str) -> str:
        """Connect an account through the fake's wide face."""
        record = await _fake(purger).provision(identity=identity, credential=credential())
        return record.reference

    async def reprovision(self, purger: object, reference: str) -> None:
        """Re-provision ``reference`` through the fake's wide face."""
        await _fake(purger).reprovision(
            reference, identity="rotated", credential=credential("rotated")
        )

    async def disconnect(self, purger: object, reference: str) -> None:
        """Disconnect ``reference`` through the fake's wide face."""
        await _fake(purger).disconnect(reference)


class TestFakeConnectionProvisionerContract(FakeConnectionHooks, ConnectionProvisionerContract):
    """Runs the canonical fake through the shared ``ConnectionProvisioner`` suite."""

    @pytest.fixture
    def provisioner(self) -> ConnectionProvisioner:
        """An empty provisioner over a keyring of its own."""
        return FakeConnectionProvisioner()


class TestFakeConnectionPurgerContract(FakeConnectionHooks, ConnectionPurgerContract):
    """Runs the canonical fake through the shared ``ConnectionPurger`` suite.

    The same class under the narrow face's name, which is ADR-0153 §2's "one
    implementation satisfies both faces with one method" rather than a shortcut:
    two fakes would be the drift that clause forbids.
    """

    @pytest.fixture
    def purger(self) -> ConnectionPurger:
        """An empty purger over a keyring of its own."""
        return FakeConnectionProvisioner()
