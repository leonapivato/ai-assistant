"""Shared conformance suite for the MemoryWriter Protocol (ADR-0028 §8).

Every ``MemoryWriter`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`MemoryWriterContract` and overrides two fixtures:

* ``make_writer`` — a factory building the writer under test over a *given*
  store and policy. It has to be a factory rather than a ready-made writer: a
  writer holds its own policy and exposes neither it nor its store, so a suite
  handed only a writer could neither drive a particular ruling nor see what was
  persisted. Supplying both collaborators is what makes the obligations below
  observable at all.
* ``writer`` — one ready-made writer, for the structural check (and the
  evidence the triad check reads).

The obligations are the ones ADR-0028 §8 lists, and no more: conflicts are
resolved *before* the policy is asked and their ids are carried on the proposal
it sees; ``ACCEPT`` stores the record and returns its id; ``STORE_TEMPORARY``
stores it with an expiry; ``REJECT`` and ``ASK_USER`` write nothing and return a
``None`` record id; ``MERGE`` folds into the named target, keeps the target's id
and returns it; and a ``MERGE`` naming a target absent from the conflicts raises
``MemoryStoreError`` rather than storing the proposal as new.

It deliberately does **not** pin the conflict threshold, the conflict limit, the
constructor's tuning check, or the fold's own rule — those are one
implementation's tuning and `memory`'s semantics, and a suite that pinned them
would stop being a contract. Nor does it pin clock handling: a writer with no
clock at all conforms, so ``MemoryIngestor``'s naive-clock guard is asserted in
``test_ingest.py`` where it belongs (ADR-0028 §4b).

This module is intentionally not named ``test_*`` so pytest does not collect the
abstract base directly; it is collected via a ``Test``-prefixed subclass.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.protocols import MemoryWriter
from ai_assistant.core.types import (
    DataTier,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryRecord,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    Provenance,
)
from ai_assistant.testing import FakeMemoryPolicy, FakeMemoryStore

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore

#: Builds the writer under test over the store and policy the suite supplies.
type WriterFactory = Callable[[MemoryStore, MemoryPolicy], MemoryWriter]

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

#: The store's clock, fixed far enough back that any expiry a writer stamps from
#: any clock is still in the future. The contract fixes no writer clock, so a
#: store reading "now" as the present could hide a just-stored temporary record
#: behind ADR-0007's read-time retention and fail a conforming writer.
_LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)

_CONTENT = "prefers concise emails"


def _long_ago() -> datetime:
    return _LONG_AGO


def _preference(
    record_id: str, content: str = _CONTENT, *, confidence: float = 0.6
) -> MemoryRecord:
    return PreferenceMemory(
        id=record_id,
        content=content,
        preference=content,
        provenance=Provenance(
            source=MemorySource.OBSERVED, confidence=confidence, last_updated=_WHEN
        ),
    )


def _proposal(record: MemoryRecord) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(proposed=record, rationale="because", sensitivity=DataTier.PERSONAL)


class _MergeToAbsentTargetPolicy:
    """Always asks to merge into a record that is not among the conflicts."""

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
    ) -> MemoryDecision:
        """Name a target the writer was never offered."""
        return MemoryDecision(
            kind=MemoryDecisionKind.MERGE, merge_into="ghost", reason="contract: misdirection"
        )


class MemoryWriterContract:
    """The behavioural contract every ``MemoryWriter`` must satisfy."""

    @pytest.fixture
    def make_writer(self) -> WriterFactory:
        """Override in a subclass: build the writer under test over these two."""
        raise NotImplementedError

    @pytest.fixture
    def writer(self) -> MemoryWriter:
        """Override in a subclass: one writer, however it likes to be built."""
        raise NotImplementedError

    def test_conforms_to_protocol(self, writer: MemoryWriter) -> None:
        assert isinstance(writer, MemoryWriter)

    async def test_conflicts_are_resolved_before_the_policy_is_asked(
        self, make_writer: WriterFactory
    ) -> None:
        """The caller supplies no conflicts, so the writer must find them itself.

        And the proposal the policy sees must name them, so a decision is
        auditable against what it was ruled on.
        """
        store = FakeMemoryStore(now=_long_ago)
        await store.add(_preference("existing"))
        policy = FakeMemoryPolicy(MemoryDecisionKind.REJECT)

        await make_writer(store, policy).ingest(_proposal(_preference("new")))

        assert [record.id for record in policy.calls[0].conflicts] == ["existing"]
        assert policy.last_proposal.conflicts == ["existing"]

    async def test_accept_stores_the_record_and_returns_its_id(
        self, make_writer: WriterFactory
    ) -> None:
        store = FakeMemoryStore(now=_long_ago)
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.ACCEPT))

        result = await writer.ingest(_proposal(_preference("new")))

        assert result.decision.kind is MemoryDecisionKind.ACCEPT
        assert result.record_id == "new"
        # Stored by the time `ingest` returned: the result reports an id written,
        # so a writer that queued the proposal for later would be claiming
        # something this result type cannot say (ADR-0028 §Consequences).
        assert await store.get("new") is not None

    async def test_store_temporary_stores_the_record_with_an_expiry(
        self, make_writer: WriterFactory
    ) -> None:
        """The expiry is stamped from the writer's own clock, whatever that is.

        Its *value* is not pinned — the contract fixes no clock — but it must be
        set, and aware, since a naive deadline raises ``TypeError`` at the first
        comparison inside a store.
        """
        store = FakeMemoryStore(now=_long_ago)
        policy = FakeMemoryPolicy(MemoryDecisionKind.STORE_TEMPORARY, ttl=timedelta(days=1))

        result = await make_writer(store, policy).ingest(_proposal(_preference("new")))

        assert result.decision.kind is MemoryDecisionKind.STORE_TEMPORARY
        assert result.record_id == "new"
        stored = await store.get("new")
        assert stored is not None
        assert stored.expires_at is not None
        assert stored.expires_at.tzinfo is not None

    @pytest.mark.parametrize(
        "kind", [MemoryDecisionKind.REJECT, MemoryDecisionKind.ASK_USER], ids=str
    )
    async def test_a_declined_ruling_writes_nothing(
        self, make_writer: WriterFactory, kind: MemoryDecisionKind
    ) -> None:
        store = FakeMemoryStore(now=_long_ago)

        result = await make_writer(store, FakeMemoryPolicy(kind)).ingest(
            _proposal(_preference("new"))
        )

        assert result.decision.kind is kind
        assert result.record_id is None
        assert await store.export() == []

    async def test_merge_folds_into_the_target_and_keeps_its_id(
        self, make_writer: WriterFactory
    ) -> None:
        """The ruling that consolidates rather than accretes is *applied*.

        What the fold does to content, evidence and confidence is `memory`'s own
        rule and is not pinned here. That it lands on the target's id, and mints
        no second record, is the contract.
        """
        store = FakeMemoryStore(now=_long_ago)
        await store.add(_preference("existing"))
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.MERGE))

        result = await writer.ingest(_proposal(_preference("new", confidence=0.9)))

        assert result.decision.kind is MemoryDecisionKind.MERGE
        assert result.record_id == "existing"
        assert [record.id for record in await store.export()] == ["existing"]

    async def test_merge_naming_an_absent_target_is_refused(
        self, make_writer: WriterFactory
    ) -> None:
        """Storing the proposal as new would create the duplicate the merge
        existed to prevent, while reporting success."""
        store = FakeMemoryStore(now=_long_ago)
        writer = make_writer(store, _MergeToAbsentTargetPolicy())

        with pytest.raises(MemoryStoreError):
            await writer.ingest(_proposal(_preference("new")))

        assert await store.get("new") is None
