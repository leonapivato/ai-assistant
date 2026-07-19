"""The canonical FakeMemoryStore passes the shared MemoryStore conformance suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeMemoryStore``
as a stand-in for a real store: it is held to the same contract as
``InMemoryMemoryStore`` and ``SqliteMemoryStore``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from memory_store_contract import MemoryStoreContract

from ai_assistant.testing import FakeMemoryStore

if TYPE_CHECKING:
    from ai_assistant.core.protocols import MemoryStore


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


class TestFakeMemoryStoreContract(MemoryStoreContract):
    """Runs FakeMemoryStore through the shared MemoryStore conformance suite."""

    @pytest.fixture
    def store(self) -> MemoryStore:
        return FakeMemoryStore(now=_fixed_now)
