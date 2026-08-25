"""The durable ledger passes both invocation conformance suites (ADR-0192 §2).

``SqliteAuditTrail`` is ADR-0137 §2's *primary production implementation* — the
consumer whose demands shape the contract — so the suites run against it as well
as against the canonical fake, and it is the subject that carries the cases the
fake can only skip: a store that outlives the object holding it, which is what the
restart and two-instance arms are about.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from invocation_ledger_contract import (
    InvocationCompleterContract,
    InvocationLedgerContract,
    LedgerSubject,
)

from ai_assistant.permissions.audit import SqliteAuditTrail
from ai_assistant.testing.cancellation import ThreadSuspension

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from ai_assistant.testing.cancellation import SuspendedCall

#: Which private method each contract operation does its SQL in. Arming *that* is
#: what parks the worker inside the connection's turn — under ``async with
#: self._lock`` and inside the ``to_thread`` the event loop cannot interrupt — so a
#: second caller genuinely queues rather than racing on an event-loop tick.
_SYNC_METHODS = {
    "claim_invocation": "_claim_sync",
    "complete_invocation": "_complete_sync",
    "open_invocations": "_open_invocations_sync",
    "recent_invocations": "_joined_sync",
    "export_invocations": "_joined_sync",
    "clear": "_clear_sync",
}


class SqliteLedgerHarness:
    """Builds ``SqliteAuditTrail`` subjects on files under one ``tmp_path``.

    On **files** rather than ``":memory:"``: ``store_of`` has to name something a
    second object can open, and that is the whole point of the two arms the fake
    skips. Every trail opened is closed when the case ends.
    """

    def __init__(self, root: Path) -> None:
        """Open trails under ``root``, numbering each fresh store."""
        self._root = root
        self._opened: list[SqliteAuditTrail] = []
        self._stores: dict[int, Path] = {}
        self._suspensions: list[ThreadSuspension] = []

    def open(
        self,
        *,
        now: Callable[[], Any] | None = None,
        identifiers: Any = None,
        store: object | None = None,
    ) -> LedgerSubject:
        """Return a trail over ``store``, or over a fresh file."""
        fresh = self._root / f"t{len(self._stores)}.db"
        path = store if isinstance(store, Path) else fresh
        trail = (
            SqliteAuditTrail(path=path, identifiers=identifiers)
            if now is None
            else SqliteAuditTrail(path=path, now=now, identifiers=identifiers)
        )
        self._opened.append(trail)
        self._stores[id(trail)] = path
        subject: LedgerSubject = trail
        return subject

    def store_of(self, subject: LedgerSubject) -> object | None:
        """The file this trail was opened on, which a second object can open too."""
        return self._stores.get(id(subject))

    def arm(self, subject: LedgerSubject, operation: str) -> SuspendedCall:
        """Park ``operation``'s worker inside the connection's turn.

        The first worker to arrive blocks and every later one runs free, so the
        case suspends the call under test rather than a setup write.
        """
        trail = subject
        assert isinstance(trail, SqliteAuditTrail)
        attribute = _SYNC_METHODS[operation]
        original = getattr(trail, attribute)
        suspension = ThreadSuspension()
        armed = threading.Event()

        def blocking(*args: object) -> object:
            if not armed.is_set():
                armed.set()
                suspension.hold()
            return original(*args)

        setattr(trail, attribute, blocking)
        self._suspensions.append(suspension)
        return suspension

    def dispose(self) -> None:
        """Release anything still parked, then close every trail opened."""
        for suspension in self._suspensions:
            suspension.release()
        for trail in self._opened:
            trail.close()


@pytest.fixture
def sqlite_harness(tmp_path: Path) -> Iterator[SqliteLedgerHarness]:
    """A harness whose trails live under ``tmp_path`` and are closed after the case."""
    harness = SqliteLedgerHarness(tmp_path)
    harness._suspensions = []
    try:
        yield harness
    finally:
        harness.dispose()


class TestSqliteInvocationCompleterContract(InvocationCompleterContract):
    """Runs the durable ledger through the narrow face's shared suite."""

    @pytest.fixture
    def harness(self, sqlite_harness: SqliteLedgerHarness) -> SqliteLedgerHarness:
        return sqlite_harness


class TestSqliteInvocationLedgerContract(InvocationLedgerContract):
    """Runs the durable ledger through the wide face's shared suite."""

    @pytest.fixture
    def harness(self, sqlite_harness: SqliteLedgerHarness) -> SqliteLedgerHarness:
        return sqlite_harness
