"""``FakeEgressBinder`` against the shared ``EgressBinder`` suite (ADR-0152 §13).

The concrete binding CONTRIBUTING's triad rule requires: without it the abstract
suite collects nothing and the canonical fake is unverified, however many files
exist (``tests/core/test_protocol_triad.py`` checks that these assertions
*actually ran*).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from egress_binder_contract import ENDPOINT, IDENTITY, REFERENCE, EgressBinderContract

from ai_assistant.core.types import ProvisioningState
from ai_assistant.testing import FakeEgressBinder

if TYPE_CHECKING:
    from ai_assistant.core.protocols import EgressBinder
    from ai_assistant.core.types import ToolDefinition
    from ai_assistant.testing.cancellation import SuspendedCall


def _fake(binder: EgressBinder) -> FakeEgressBinder:
    """The subject under its wider face, which is the same object (ADR-0153 §2's shape)."""
    return cast("FakeEgressBinder", binder)


class TestFakeEgressBinderContract(EgressBinderContract):
    """The canonical fake honours every obligation ADR-0152 states."""

    @pytest.fixture
    def binder(self) -> EgressBinder:
        """An empty fake binder."""
        return FakeEgressBinder()

    def register(self, binder: EgressBinder, tool: ToolDefinition) -> None:
        """Hold ``tool`` as a registry original bound to no account."""
        _fake(binder).register(tool)

    def register_egress(  # noqa: PLR0913 — one parameter per fact a connection record carries
        self,
        binder: EgressBinder,
        tool: ToolDefinition,
        *,
        reference: str = REFERENCE,
        identity: str = IDENTITY,
        transport_endpoint: str = ENDPOINT,
        state: ProvisioningState = ProvisioningState.ACTIVE,
    ) -> None:
        """Register ``tool`` against a connected account."""
        _fake(binder).register_egress(
            tool,
            reference=reference,
            identity=identity,
            transport_endpoint=transport_endpoint,
            state=state,
        )

    def set_connection(
        self,
        binder: EgressBinder,
        reference: str,
        *,
        identity: str,
        state: ProvisioningState = ProvisioningState.ACTIVE,
    ) -> None:
        """Rewrite the record ``reference`` names."""
        _fake(binder).set_connection(reference, identity=identity, state=state)

    def remove_connection(self, binder: EgressBinder, reference: str) -> None:
        """Drop the record ``reference`` names."""
        _fake(binder).remove_connection(reference)

    def fail_next_read(self, binder: EgressBinder) -> None:
        """Arm the next read to raise ``ConnectionStoreError``."""
        _fake(binder).fail_next_read()

    def suspend_next_read(self, binder: EgressBinder) -> SuspendedCall:
        """Hold the next read open."""
        return _fake(binder).suspend_next_read()

    def reads(self, binder: EgressBinder) -> tuple[str, ...]:
        """Every reference read so far."""
        return _fake(binder).reads()

    def canonicalising_nothing(self) -> EgressBinder:
        """A fake whose canonicaliser set has been narrowed to nothing."""
        return FakeEgressBinder(canonicalises=())
