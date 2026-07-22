"""MemoryIngestor — the production writer — passes the shared MemoryWriter suite.

The triad check demands only the *fake's* binding, so this file is what ADR-0028
§8 adds on top: a suite bound only to the double certifies the double while the
production writer drifts, and ``MemoryIngestor`` is what ``LearningLoop``
delegates to. ``test_ingest.py`` stays implementation tests and is not this
binding.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from memory_writer_contract import MemoryWriterContract, WriterFactory

from ai_assistant.memory import DefaultMemoryPolicy, InMemoryMemoryStore, MemoryIngestor

if TYPE_CHECKING:
    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore, MemoryWriter


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


class TestMemoryIngestorContract(MemoryWriterContract):
    """Runs MemoryIngestor through the shared MemoryWriter conformance suite."""

    @pytest.fixture
    def make_writer(self) -> WriterFactory:
        def build(store: MemoryStore, policy: MemoryPolicy) -> MemoryWriter:
            return MemoryIngestor(store=store, policy=policy, now=_fixed_now)

        return build

    @pytest.fixture
    def writer(self) -> MemoryWriter:
        return MemoryIngestor(
            store=InMemoryMemoryStore(now=_fixed_now), policy=DefaultMemoryPolicy(), now=_fixed_now
        )
