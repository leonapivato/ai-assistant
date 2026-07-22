"""A canonical :class:`~ai_assistant.core.protocols.MemoryWriter` fake.

The shared test double for the ``MemoryWriter`` contract (ADR-0028), so a
subsystem that commits memory through the write path — `orchestration`, above
all — can exercise it *without importing the memory subsystem's internals*
(CLAUDE.md golden rule 1).

It is a minimal, contract-correct writer over an injected store and policy: it
resolves conflicts, asks the policy to rule, and applies the ruling. Only the
behaviour pinned by the shared ``MemoryWriter`` conformance suite is contract.
Its conflict heuristic and its merge rule are deliberately *not* — those are
``MemoryIngestor``'s tuning and `memory`'s semantics, and a fake that promised
them would be a second copy of one implementation.

Beyond the contract it records every proposal it was handed on :attr:`calls`, so
a test can assert what its subject actually delegated.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import MemoryDecisionKind, MemoryIngestResult, MemoryKind, Provenance

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore
    from ai_assistant.core.types import MemoryDecision, MemoryRecord, MemoryUpdateProposal

_DEFAULT_CONFLICT_THRESHOLD = 0.75
_DEFAULT_CONFLICT_LIMIT = 5


def _utcnow() -> datetime:
    return datetime.now(UTC)


class FakeMemoryWriter:
    """A ``MemoryWriter`` test double that really writes to an injected store.

    Structurally implements
    :class:`~ai_assistant.core.protocols.MemoryWriter`. Real rather than inert
    on purpose: a writer that recorded proposals and stored nothing would let a
    consumer's test pass while its closed loop stayed open, which is exactly the
    failure ADR-0028 §Consequences names as the standing cost of this seam.
    """

    def __init__(
        self,
        *,
        store: MemoryStore,
        policy: MemoryPolicy,
        conflict_threshold: float = _DEFAULT_CONFLICT_THRESHOLD,
        conflict_limit: int = _DEFAULT_CONFLICT_LIMIT,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        """Create the fake writer.

        Args:
            store: Where accepted memories are persisted and conflicts sought.
                A consumer's test must pass the *same* store its subject
                retrieves from (ADR-0028 §4).
            policy: The policy that rules on each proposal.
            conflict_threshold: Minimum retrieval score for an existing record
                to count as conflicting.
            conflict_limit: Maximum number of conflict candidates considered.
            now: Clock used to stamp expiry on temporary stores; injectable so
                a consumer's turn is deterministic. The loop's own clock does
                *not* reach this one (ADR-0028 §4b).
        """
        self._store = store
        self._policy = policy
        self._conflict_threshold = conflict_threshold
        self._conflict_limit = conflict_limit
        self._now = now
        self.calls: list[MemoryUpdateProposal] = []

    async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        """Record the proposal, then resolve, rule and apply."""
        self.calls.append(proposal.model_copy(deep=True))
        conflicts = await self._conflicts_for(proposal.proposed)
        proposal = proposal.model_copy(update={"conflicts": [record.id for record in conflicts]})
        decision = await self._policy.decide(proposal, conflicts=conflicts)
        record_id = await self._apply(decision, proposal.proposed, conflicts)
        return MemoryIngestResult(decision=decision, record_id=record_id)

    async def _conflicts_for(self, record: MemoryRecord) -> list[MemoryRecord]:
        matches = await self._store.search(
            record.content,
            limit=self._conflict_limit + 1,
            kinds=[MemoryKind(record.kind)],
        )
        conflicts = [
            match
            for match in matches
            if match.id != record.id and (match.score or 0.0) >= self._conflict_threshold
        ]
        return conflicts[: self._conflict_limit]

    async def _apply(
        self,
        decision: MemoryDecision,
        proposed: MemoryRecord,
        conflicts: list[MemoryRecord],
    ) -> str | None:
        match decision.kind:
            case MemoryDecisionKind.ACCEPT:
                return await self._store.add(proposed)
            case MemoryDecisionKind.STORE_TEMPORARY:
                return await self._store.add(
                    proposed.model_copy(update={"expires_at": self._expiry(decision.ttl)})
                )
            case MemoryDecisionKind.MERGE:
                target = next((c for c in conflicts if c.id == decision.merge_into), None)
                if target is None:
                    msg = f"MERGE target {decision.merge_into!r} is not among the conflicts"
                    raise MemoryStoreError(msg)
                return await self._store.add(_merge(target, proposed))
            case _:  # REJECT, ASK_USER — nothing is written.
                return None

    def _expiry(self, ttl: timedelta | None) -> datetime | None:
        """Stamp an expiry ``ttl`` from now, normalising a naive reading to UTC.

        ``model_copy(update=...)`` skips validators, so a naive ``expires_at``
        would reach the store exactly as it left here and raise ``TypeError`` at
        the first comparison inside it.
        """
        if ttl is None:
            return None
        now = self._now()
        return (now if now.tzinfo is not None else now.replace(tzinfo=UTC)) + ttl


def _merge(target: MemoryRecord, incoming: MemoryRecord) -> MemoryRecord:
    """Fold ``incoming`` into ``target``, keeping the target's id.

    A minimal fold — newer content wins, evidence is unioned, confidence taken
    as the maximum. Not part of the contract: the fold's rule is `memory`'s own,
    and the conformance suite deliberately does not pin it.
    """
    provenance = Provenance(
        source=incoming.provenance.source,
        confidence=max(target.provenance.confidence, incoming.provenance.confidence),
        evidence=list(dict.fromkeys([*target.provenance.evidence, *incoming.provenance.evidence])),
        last_updated=incoming.provenance.last_updated,
    )
    return incoming.model_copy(update={"id": target.id, "provenance": provenance})
