"""The canonical FakeMemoryWriter passes the shared MemoryWriter suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeMemoryWriter``
as a stand-in for a real write path: it is held to the same contract as
``MemoryIngestor`` (see ``test_ingest_contract.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from memory_writer_contract import MemoryWriterContract, WriterFactory

from ai_assistant.core.types import (
    DataTier,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    Provenance,
)
from ai_assistant.testing import FakeMemoryPolicy, FakeMemoryStore, FakeMemoryWriter

if TYPE_CHECKING:
    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore, MemoryWriter


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


class TestFakeMemoryWriterContract(MemoryWriterContract):
    """Runs FakeMemoryWriter through the shared MemoryWriter conformance suite."""

    @pytest.fixture
    def make_writer(self) -> WriterFactory:
        def build(store: MemoryStore, policy: MemoryPolicy) -> MemoryWriter:
            return FakeMemoryWriter(store=store, policy=policy, now=_fixed_now)

        return build

    @pytest.fixture
    def writer(self) -> MemoryWriter:
        return FakeMemoryWriter(
            store=FakeMemoryStore(now=_fixed_now), policy=FakeMemoryPolicy(), now=_fixed_now
        )


# Behaviour specific to FakeMemoryWriter, beyond the shared contract: it records
# what it was handed, which is what makes it useful to a consumer's tests.


async def test_every_proposal_is_recorded_as_handed_over() -> None:
    store = FakeMemoryStore(now=_fixed_now)
    writer = FakeMemoryWriter(store=store, policy=FakeMemoryPolicy(), now=_fixed_now)
    proposal = MemoryUpdateProposal(
        proposed=PreferenceMemory(
            id="pref-1",
            content="prefers concise emails",
            preference="prefers concise emails",
            provenance=Provenance(
                source=MemorySource.OBSERVED, confidence=0.6, last_updated=_fixed_now()
            ),
        ),
        rationale="because",
        sensitivity=DataTier.PERSONAL,
    )

    await writer.ingest(proposal)

    assert [call.proposed.id for call in writer.calls] == ["pref-1"]
    # A snapshot, not the caller's object: mutating the proposal afterwards
    # cannot reach what was recorded.
    assert writer.calls[0] is not proposal
