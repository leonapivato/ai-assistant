"""The canonical FakeMemoryWriter passes the shared MemoryWriter suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeMemoryWriter``
as a stand-in for a real write path: it is held to the same contract as
``MemoryIngestor`` (see ``test_ingest_contract.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from memory_writer_contract import MemoryWriterContract, WriterFactory

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    DataTier,
    MemoryDecisionKind,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    Provenance,
    Validity,
)
from ai_assistant.testing import FakeMemoryPolicy, FakeMemoryStore, FakeMemoryWriter

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore, MemoryWriter


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


def _proposal(record_id: str) -> MemoryUpdateProposal:
    content = "prefers concise emails"
    return MemoryUpdateProposal(
        proposed=PreferenceMemory(
            id=record_id,
            content=content,
            preference=content,
            provenance=Provenance(
                source=MemorySource.OBSERVED, confidence=0.6, last_updated=_fixed_now()
            ),
        ),
        rationale="because",
        sensitivity=DataTier.PERSONAL,
    )


class TestFakeMemoryWriterContract(MemoryWriterContract):
    """Runs FakeMemoryWriter through the shared MemoryWriter conformance suite."""

    @pytest.fixture
    def make_writer(self) -> WriterFactory:
        def build(
            store: MemoryStore,
            policy: MemoryPolicy,
            *,
            id_factory: Callable[[], str] | None = None,
        ) -> MemoryWriter:
            if id_factory is None:
                return FakeMemoryWriter(store=store, policy=policy, now=_fixed_now)
            return FakeMemoryWriter(
                store=store, policy=policy, now=_fixed_now, id_factory=id_factory
            )

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
    proposal = _proposal("pref-1")

    await writer.ingest(proposal)

    assert [call.proposed.id for call in writer.calls] == ["pref-1"]
    # A snapshot, not the caller's object: mutating the proposal afterwards
    # cannot reach what was recorded.
    assert writer.calls[0] is not proposal


async def test_a_non_utc_clock_is_converted_not_merely_accepted() -> None:
    """The expiry write skips validators, so ADR-0023 §2's UTC has to happen here.

    Asserted on ``tzinfo``, not only on the instant: an equality check alone
    passes for a ``+02:00`` value, which is exactly the state §2 forbids — and
    which a store's expiry index would then be computed from. ``MemoryIngestor``
    converts; a canonical fake that merely accepted would certify a consumer
    against state the production writer refuses.
    """
    store = FakeMemoryStore(now=_fixed_now)
    berlin = timezone(timedelta(hours=2))
    writer = FakeMemoryWriter(
        store=store,
        policy=FakeMemoryPolicy(MemoryDecisionKind.STORE_TEMPORARY, ttl=timedelta(days=1)),
        now=lambda: datetime(2026, 6, 1, 2, tzinfo=berlin),
    )

    await writer.ingest(_proposal("pref-1"))

    stored = await store.get("pref-1")
    assert stored is not None
    assert stored.expires_at == datetime(2026, 6, 2, tzinfo=UTC)
    assert stored.expires_at.tzinfo is UTC


async def test_an_unrepresentable_temporary_ttl_is_the_subsystems_error() -> None:
    """A ttl past the representable date range fails the way the real one fails.

    ``MemoryIngestor`` translates the ``OverflowError`` into a
    ``MemoryStoreError`` at this boundary; a fake leaking the arithmetic error
    would have a consumer handling the wrong exception in production.
    """
    store = FakeMemoryStore(now=_fixed_now)
    writer = FakeMemoryWriter(
        store=store,
        policy=FakeMemoryPolicy(MemoryDecisionKind.STORE_TEMPORARY, ttl=timedelta.max),
        now=_fixed_now,
    )

    with pytest.raises(MemoryStoreError, match="overflows"):
        await writer.ingest(_proposal("pref-1"))

    assert await store.export() == []


async def test_supersede_refuses_a_future_dated_target_without_writing() -> None:
    """The fake carries the same data-integrity floor as ``MemoryIngestor``.

    A producer-set ``valid_from`` at or after the writer's clock would close to an
    empty/inverted window the durable store rejects on decode, so the fake refuses
    before the write rather than let a consumer's test pass on state the production
    writer could not persist (issue #306).
    """
    store = FakeMemoryStore(now=lambda: datetime(2026, 10, 1, tzinfo=UTC))
    await store.add(
        PreferenceMemory(
            id="existing",
            content="prefers concise emails",  # matches `_proposal`, so it is a conflict
            preference="prefers concise emails",
            validity=Validity(valid_from=datetime(2026, 9, 1, tzinfo=UTC)),  # after _fixed_now
            provenance=Provenance(
                source=MemorySource.INFERRED, confidence=0.6, last_updated=_fixed_now()
            ),
        )
    )
    before = await store.export()
    writer = FakeMemoryWriter(
        store=store, policy=FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), now=_fixed_now
    )

    with pytest.raises(MemoryStoreError, match="valid_from"):
        await writer.ingest(_proposal("correction"))

    assert await store.export() == before  # fail-closed: nothing written, target untouched


async def test_supersede_never_extends_a_targets_existing_window() -> None:
    """The fake keeps a target's earlier ``valid_until`` — retirement never resurrects.

    Mirrors ``MemoryIngestor``: a target self-closing before the writer clock keeps
    that earlier end (``min``), so a fake regressing to a bare ``valid_until = now``
    that pushed the end out is caught.
    """
    already_closes = datetime(2026, 3, 1, tzinfo=UTC)  # before the writer's 2026-06-01 clock
    store = FakeMemoryStore(now=lambda: datetime(2026, 2, 1, tzinfo=UTC))
    await store.add(
        PreferenceMemory(
            id="existing",
            content="prefers concise emails",
            preference="prefers concise emails",
            validity=Validity(valid_until=already_closes),
            provenance=Provenance(
                source=MemorySource.INFERRED, confidence=0.6, last_updated=_fixed_now()
            ),
        )
    )
    writer = FakeMemoryWriter(
        store=store, policy=FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), now=_fixed_now
    )

    result = await writer.ingest(_proposal("correction"))

    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    retired = next(record for record in await store.export() if record.id == "existing")
    assert retired.validity.valid_until == already_closes  # not extended to the writer clock
