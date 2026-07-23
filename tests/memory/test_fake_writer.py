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


# The bounded-window close safeguards, mirrored from MemoryIngestor
# (test_ingest.py): the fake duplicates `_close_window`, so a fake regressing to a
# bare `valid_until = now` would extend a bounded target's window or persist an
# inverted one under clock skew. The shared suite deliberately pins no clock
# (ADR-0028 §4b), so these live here, where the fake's clock is injectable.


def _inferred_target(*, validity: Validity) -> PreferenceMemory:
    content = "prefers concise emails"  # matches `_proposal`, so it is a conflict
    return PreferenceMemory(
        id="existing",
        content=content,
        preference=content,
        validity=validity,
        provenance=Provenance(
            source=MemorySource.INFERRED, confidence=0.6, last_updated=_fixed_now()
        ),
    )


async def test_supersede_never_extends_a_bounded_targets_window() -> None:
    """The fake keeps a target's earlier ``valid_until`` — retirement never prolongs."""
    already_closes = datetime(2026, 3, 1, tzinfo=UTC)  # earlier than the writer clock
    store = FakeMemoryStore(now=lambda: datetime(2026, 2, 1, tzinfo=UTC))
    await store.add(_inferred_target(validity=Validity(valid_until=already_closes)))
    writer = FakeMemoryWriter(
        store=store, policy=FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), now=_fixed_now
    )

    result = await writer.ingest(_proposal("correction"))

    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    retired = next(record for record in await store.export() if record.id == "existing")
    assert retired.validity.valid_until == already_closes  # not extended to the writer clock


async def test_supersede_refuses_a_close_before_the_targets_valid_from() -> None:
    """The fake refuses an inverted close and leaves the target live, as the real one does."""
    starts_later = datetime(2026, 9, 1, tzinfo=UTC)  # after the writer clock
    store = FakeMemoryStore(now=lambda: datetime(2026, 10, 1, tzinfo=UTC))
    await store.add(_inferred_target(validity=Validity(valid_from=starts_later)))
    before = await store.export()
    writer = FakeMemoryWriter(
        store=store, policy=FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), now=_fixed_now
    )

    with pytest.raises(MemoryStoreError, match="not after its valid_from"):
        await writer.ingest(_proposal("correction"))

    assert await store.export() == before  # fail-closed: nothing written, target untouched
