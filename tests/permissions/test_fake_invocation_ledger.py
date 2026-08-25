"""The canonical fake passes both invocation conformance suites (ADR-0192 §2).

This is what lets ``tools/`` and ``orchestration/`` trust
``ai_assistant.testing.FakeInvocationLedger`` and
``FakeInvocationCompleter`` as stand-ins: they are the same object, held to the
same consume, the same append order and the same detachment a durable ledger is.

Both suites run against it, and the narrow one is not merely inherited: ADR-0192
§2 has ``orchestration``'s recovery scan hold ``InvocationCompleter`` alone, so a
subject bound only to that face is the composition that consumer actually gets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from invocation_ledger_contract import (
    InvocationCompleterContract,
    InvocationLedgerContract,
    LedgerSubject,
)

from ai_assistant.testing import FakeAuditTrail

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.testing.cancellation import SuspendedCall


class FakeLedgerHarness:
    """Builds :class:`FakeAuditTrail` subjects for the shared suites.

    ``store_of`` answers ``None``: a dict store does not outlive the object that
    holds it, so the restart and two-instance cases skip **with their reason
    stated** rather than being omitted — they are proved on the ``sqlite3`` ledger,
    which is the implementation whose store genuinely outlives a process.
    """

    def open(
        self,
        *,
        now: Callable[[], Any] | None = None,
        identifiers: Any = None,
        store: object | None = None,
    ) -> LedgerSubject:
        """Return a fresh trail; ``store`` is never satisfiable here."""
        assert store is None, "this harness reports no shareable store"
        built = (
            FakeAuditTrail(identifiers=identifiers)
            if now is None
            else FakeAuditTrail(now=now, identifiers=identifiers)
        )
        return cast_subject(built)

    def store_of(self, subject: LedgerSubject) -> object | None:
        """A dict store cannot be opened twice."""
        del subject
        return None

    def arm(self, subject: LedgerSubject, operation: str) -> SuspendedCall:
        """Suspend the next entry into the one modelled resource.

        The fake models a single resource and every method enters it, so ``arm``
        ignores which operation it is handed — exactly as ``AuditTrailContract``'s
        own binding does. The suite arms immediately before the call under test,
        which is what makes that sufficient.
        """
        del operation
        trail = subject
        assert isinstance(trail, FakeAuditTrail)
        return trail.suspend_next_operation()


def cast_subject(trail: FakeAuditTrail) -> LedgerSubject:
    """Read one object as the union of faces ADR-0192 §2 says it satisfies."""
    subject: LedgerSubject = trail
    return subject


class TestFakeInvocationCompleterContract(InvocationCompleterContract):
    """Runs the fake through the narrow face's shared conformance suite."""

    @pytest.fixture
    def harness(self) -> FakeLedgerHarness:
        return FakeLedgerHarness()


class TestFakeInvocationLedgerContract(InvocationLedgerContract):
    """Runs the fake through the wide face's shared conformance suite."""

    @pytest.fixture
    def harness(self) -> FakeLedgerHarness:
        return FakeLedgerHarness()
