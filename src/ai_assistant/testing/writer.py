"""A canonical :class:`~ai_assistant.core.protocols.MemoryWriter` fake.

The shared test double for the ``MemoryWriter`` contract (ADR-0028), so a
subsystem that commits memory through the write path — `orchestration`, above
all — can exercise it *without importing the memory subsystem's internals*
(CLAUDE.md golden rule 1).

It is a minimal, contract-correct writer over an injected store and policy: it
resolves conflicts, asks the policy to rule, and applies the ruling. Only the
behaviour pinned by the shared ``MemoryWriter`` conformance suite is contract —
which, since ADR-0040 §5a, includes ``SUPERSEDE`` carrying nothing of the target
across, ``REINFORCE`` retaining both records' evidence, and the two fold refusals
(§5b). Its conflict heuristic and how a ``REINFORCE`` combines content and
confidence are deliberately *not* — those are ``MemoryIngestor``'s tuning and
`memory`'s semantics, and a fake that promised them would be a second copy of one
implementation.

Beyond the contract it records every proposal it was handed on :attr:`calls`, so
a test can assert what its subject actually delegated.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    MemoryDecisionKind,
    MemoryIngestResult,
    MemoryKind,
    MemorySource,
    Provenance,
)

if TYPE_CHECKING:
    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore
    from ai_assistant.core.types import MemoryDecision, MemoryRecord, MemoryUpdateProposal

_DEFAULT_CONFLICT_THRESHOLD = 0.75
_DEFAULT_CONFLICT_LIMIT = 5

# The only targets a user assertion may be folded onto (ADR-0038 §2a). Held here
# rather than imported from `memory`, so the fake stays free of the subsystem's
# internals (golden rule 1) while honouring the same refusals the production
# writer does (ADR-0040 §5b).
_SUPERSEDABLE = frozenset({MemorySource.OBSERVED, MemorySource.INFERRED})


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
        now: Clock = _utcnow,
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
                *not* reach this one (ADR-0028 §4b). Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, the same guard
                ``MemoryIngestor`` carries — which is what closes #186, where
                this fake accepted a clock whose ``utcoffset()`` is indeterminate
                and the production writer refused it.
        """
        self._store = store
        self._policy = policy
        self._conflict_threshold = conflict_threshold
        self._conflict_limit = conflict_limit
        self._clock = checked_clock(now, owner="FakeMemoryWriter")
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
            case MemoryDecisionKind.REINFORCE | MemoryDecisionKind.SUPERSEDE:
                target = next((c for c in conflicts if c.id == decision.target_id), None)
                if target is None:
                    msg = f"fold target {decision.target_id!r} is not among the conflicts"
                    raise MemoryStoreError(msg)
                _refuse_unsafe_fold(target, proposed)
                if decision.kind is MemoryDecisionKind.SUPERSEDE:
                    return await self._store.add(_supersede(target, proposed))
                return await self._store.add(_merge(target, proposed))
            case _:  # REJECT, ASK_USER — nothing is written.
                return None

    def _expiry(self, ttl: timedelta | None) -> datetime | None:
        """Stamp an expiry ``ttl`` from now, in UTC, failing the way a store does.

        ``model_copy(update=...)`` skips validators, so whatever this returns
        reaches the store exactly as it left here. Two things follow, and the
        production writer does both — a fake that did neither would let a
        consumer's test pass on state ``MemoryIngestor`` would have refused:

        * the reading is guarded and converted, by the same
          :func:`~ai_assistant.core.clock.checked_clock` ``MemoryIngestor``
          uses, so a naive, indeterminate or unlocalizable reading is a
          ``MemoryStoreError`` here exactly as it is there (#186); and
        * an unrepresentable deadline becomes a ``MemoryStoreError``, not the
          raw ``OverflowError`` the arithmetic raises.

        Raises:
            MemoryStoreError: If the clock's reading is not conforming, or the
                deadline is unrepresentable.
        """
        if ttl is None:
            return None
        try:
            now = self._clock()
        except ClockReadingError as exc:
            raise MemoryStoreError(str(exc)) from exc
        try:
            return now + ttl
        except OverflowError as exc:
            msg = f"temporary-store ttl {ttl!r} overflows the representable date range"
            raise MemoryStoreError(msg) from exc


def _refuse_unsafe_fold(target: MemoryRecord, incoming: MemoryRecord) -> None:
    """Refuse a fold that would destroy data, as ``MemoryIngestor`` does.

    Contract, not tuning (ADR-0040 §5b): every fold writes at the *target's* id,
    so a ``REINFORCE`` or ``SUPERSEDE`` must raise and write nothing when the
    target is ``USER_ASSERTED``, or when the incoming record is ``USER_ASSERTED``
    and the target is ``EXTERNAL``. Keyed on the records, before either arm is
    chosen. Duplicated from ``MemoryIngestor`` deliberately: the fake owes the
    same refusals but must not reach into the ``memory`` subsystem to get them
    (golden rule 1), so a consumer's test cannot pass on state the production
    writer would have refused.

    Raises:
        MemoryStoreError: If the fold is one of the two above.
    """
    if target.provenance.source is MemorySource.USER_ASSERTED:
        msg = (
            f"refusing to fold onto {target.id!r}: a {incoming.provenance.source} record may not "
            f"be folded onto a user-asserted one (ADR-0038 §3)"
        )
        raise MemoryStoreError(msg)
    if (
        incoming.provenance.source is MemorySource.USER_ASSERTED
        and target.provenance.source not in _SUPERSEDABLE
    ):
        msg = (
            f"refusing to fold onto {target.id!r}: a user assertion may not be folded onto a "
            f"{target.provenance.source} record — only OBSERVED and INFERRED beliefs may be "
            f"superseded (ADR-0038 §2a)"
        )
        raise MemoryStoreError(msg)


def _supersede(target: MemoryRecord, incoming: MemoryRecord) -> MemoryRecord:
    """Overturn ``target`` with ``incoming``, keeping only the target's id.

    Nothing of the overturned belief is carried across — not its content, its
    provenance, its ``evidence``, nor its ``confidence`` — only the id the
    surviving record is written at (ADR-0040 §5a). Contract, unlike ``_merge``'s
    fold rule: "carries nothing across" is a complete specification.
    """
    return incoming.model_copy(update={"id": target.id})


def _merge(target: MemoryRecord, incoming: MemoryRecord) -> MemoryRecord:
    """Fold ``incoming`` into ``target``, keeping the target's id.

    A minimal fold — newer content wins, confidence taken as the maximum. Only
    the evidence half is contract (ADR-0040 §5a): a ``REINFORCE`` retains
    **both** records' ``evidence``. How content and confidence combine is
    `memory`'s own rule, which the conformance suite deliberately does not pin.
    """
    provenance = Provenance(
        source=incoming.provenance.source,
        confidence=max(target.provenance.confidence, incoming.provenance.confidence),
        evidence=list(dict.fromkeys([*target.provenance.evidence, *incoming.provenance.evidence])),
        last_updated=incoming.provenance.last_updated,
    )
    return incoming.model_copy(update={"id": target.id, "provenance": provenance})
