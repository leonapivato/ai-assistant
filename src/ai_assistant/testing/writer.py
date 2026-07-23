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

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import MemoryStoreConflictError, MemoryStoreError
from ai_assistant.core.types import (
    MemoryDecisionKind,
    MemoryIngestResult,
    MemoryKind,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Provenance,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore
    from ai_assistant.core.types import MemoryDecision, MemoryRecord, MemoryUpdateProposal

_DEFAULT_CONFLICT_THRESHOLD = 0.75
_DEFAULT_CONFLICT_LIMIT = 5

#: Bound on the supersession re-mint loop, matching ``MemoryIngestor`` (ADR-0045
#: §4). Duplicated rather than imported: the fake must not reach into `memory`.
_MAX_SUPERSEDE_ATTEMPTS = 5


def _uuid() -> str:
    return str(uuid.uuid4())


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

    def __init__(  # noqa: PLR0913 — one parameter per injected collaborator plus two knobs
        self,
        *,
        store: MemoryStore,
        policy: MemoryPolicy,
        conflict_threshold: float = _DEFAULT_CONFLICT_THRESHOLD,
        conflict_limit: int = _DEFAULT_CONFLICT_LIMIT,
        now: Clock = _utcnow,
        id_factory: Callable[[], str] = _uuid,
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
            now: Clock used to stamp expiry on temporary stores and to close a
                superseded target's window; injectable so a consumer's turn is
                deterministic. The loop's own clock does *not* reach this one
                (ADR-0028 §4b). Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, the same guard
                ``MemoryIngestor`` carries — which is what closes #186, where
                this fake accepted a clock whose ``utcoffset()`` is indeterminate
                and the production writer refused it.
            id_factory: Mints the fresh id a ``SUPERSEDE`` writes its correction at
                (ADR-0045 §4); injectable so a consumer's test asserts exact ids.
                Guarded at its output by :func:`_checked_id`, the same guard
                ``MemoryIngestor`` carries, so this fake refuses a malformed factory
                exactly as the production writer does. Defaults to random UUIDs.
        """
        self._store = store
        self._policy = policy
        self._conflict_threshold = conflict_threshold
        self._conflict_limit = conflict_limit
        self._clock = checked_clock(now, owner="FakeMemoryWriter")
        self._id_factory = id_factory
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
                _refuse_unsafe_fold(target, proposed, decision.kind)
                if decision.kind is MemoryDecisionKind.SUPERSEDE:
                    return await self._apply_supersede(target, proposed)
                return await self._store.add(_merge(target, proposed))
            case _:  # REJECT, ASK_USER — nothing is written.
                return None

    async def _apply_supersede(self, target: MemoryRecord, proposed: MemoryRecord) -> str:
        """Close ``target``'s window and write ``proposed`` at a fresh id (ADR-0045 §4).

        Contract behaviour, mirroring ``MemoryIngestor``: the window-close of the
        retained target and the insert-if-absent of the correction are one atomic
        ``write_atomic`` batch (ADR-0046), the correction's id comes from the
        guarded factory and is re-minted on a bounded number of collisions, and any
        other store failure leaves the target live. A fake that rehomed the
        correction onto the target's id, or blind-upserted a colliding id, would let
        a consumer's test pass on state the production writer refuses.

        Returns:
            The correction's freshly-minted id — the id now holding the live belief.
        """
        closed_target = _close_window(target, self._now_utc())
        last_conflict: MemoryStoreConflictError | None = None
        for _ in range(_MAX_SUPERSEDE_ATTEMPTS):
            new_id = _checked_id(self._id_factory, owner="FakeMemoryWriter")
            if new_id == target.id:
                # The minted id names the retained target itself — a stored id that
                # must be re-minted (ADR-0045 §4). Writing it would make the batch
                # two writes to one id, a hard `MemoryStoreError` (ADR-0046 §3), not
                # the retryable conflict this is. Mirrors ``MemoryIngestor``.
                last_conflict = MemoryStoreConflictError(
                    f"minted id {new_id!r} names the superseded target; re-minting"
                )
                continue
            batch = [
                MemoryWrite(record=closed_target, mode=MemoryWriteMode.UPSERT),
                MemoryWrite(
                    record=_supersede(proposed, new_id),
                    mode=MemoryWriteMode.INSERT_IF_ABSENT,
                ),
            ]
            try:
                await self._store.write_atomic(batch)
            except MemoryStoreConflictError as exc:
                last_conflict = exc
                continue
            return new_id
        msg = (
            f"supersession could not mint a free id for a correction to {target.id!r} "
            f"after {_MAX_SUPERSEDE_ATTEMPTS} attempts; the target is left live and unchanged"
        )
        raise MemoryStoreError(msg) from last_conflict

    def _now_utc(self) -> datetime:
        """The guarded clock's reading, as a ``MemoryStoreError`` on a bad reading.

        Load-bearing for :meth:`_apply_supersede`'s window-close, which installs
        ``valid_until`` via ``model_copy(update=...)`` — a path pydantic never
        validates — exactly as :meth:`_expiry` is for the expiry write.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise MemoryStoreError(str(exc)) from exc

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
            return self._now_utc() + ttl
        except OverflowError as exc:
            msg = f"temporary-store ttl {ttl!r} overflows the representable date range"
            raise MemoryStoreError(msg) from exc


def _refuse_unsafe_fold(
    target: MemoryRecord, incoming: MemoryRecord, kind: MemoryDecisionKind
) -> None:
    """Refuse a fold that would destroy data, as ``MemoryIngestor`` does.

    Contract, not tuning (ADR-0040 §5b, as narrowed by ADR-0045 §5). Two refusals,
    differing in whether the ruling matters because ADR-0045 §4 made only
    ``SUPERSEDE`` mint a new id:

    - **Clause 1 — any fold onto a ``USER_ASSERTED`` target**, under either ruling.
      Kept record-keyed: the conflict signal is too weak to retire a record the
      user gave us, which the window does not change (ADR-0045 §5).
    - **Clause 2 — a ``USER_ASSERTED`` proposal onto an ``EXTERNAL`` target,
      ``REINFORCE`` only.** A ``REINFORCE`` still inherits the external id and is
      overwritten by the next sync (ADR-0038 §2a); a ``SUPERSEDE`` now gets a fresh
      id and is permitted (ADR-0045 §5b), so the arm is narrowed to ``REINFORCE``.

    Duplicated from ``MemoryIngestor`` deliberately: the fake owes the same
    refusals but must not reach into the ``memory`` subsystem to get them (golden
    rule 1), so a consumer's test cannot pass on state the production writer would
    have refused.

    Raises:
        MemoryStoreError: If the fold is one of the two above.
    """
    if target.provenance.source is MemorySource.USER_ASSERTED:
        msg = (
            f"refusing to fold onto {target.id!r}: a {incoming.provenance.source} record may not "
            f"be folded onto a user-asserted one (ADR-0038 §3, ADR-0045 §5)"
        )
        raise MemoryStoreError(msg)
    if (
        kind is MemoryDecisionKind.REINFORCE
        and incoming.provenance.source is MemorySource.USER_ASSERTED
        and target.provenance.source not in _SUPERSEDABLE
    ):
        msg = (
            f"refusing to reinforce onto {target.id!r}: a user assertion may not be reinforced "
            f"onto a {target.provenance.source} record whose id it would inherit — only OBSERVED "
            f"and INFERRED beliefs (ADR-0038 §2a, narrowed to REINFORCE by ADR-0045 §5b)"
        )
        raise MemoryStoreError(msg)


def _checked_id(id_factory: Callable[[], str], *, owner: str) -> str:
    """Read the injected id factory, guarding its output like ``MemoryIngestor``.

    The minted id is installed with ``model_copy(update=...)``, which skips
    validators, so a raising, non-``str`` or empty reading must become a
    ``MemoryStoreError`` *before* the write (ADR-0045 §4). Duplicated from the
    production writer so the fake refuses a malformed factory identically.

    Raises:
        MemoryStoreError: If the factory raises, or returns a non-``str`` or empty
            id.
    """
    try:
        minted = id_factory()
    except Exception as exc:  # any factory failure is the store's error, not the caller's
        msg = f"the id factory injected into {owner} raised while minting a supersession id"
        raise MemoryStoreError(msg) from exc
    if not isinstance(minted, str) or not minted:
        msg = f"the id factory injected into {owner} returned a non-str or empty id: {minted!r}"
        raise MemoryStoreError(msg)
    return minted


def _close_window(target: MemoryRecord, now: datetime) -> MemoryRecord:
    """Return ``target`` with its validity window closed at ``now`` (ADR-0045 §4).

    The target is retained off the read path with its window's open end brought in
    to ``now``; every other field, ``valid_from`` included, is preserved. Mirrors
    ``MemoryIngestor._close_window``, including its two robustness rules for a
    producer-set bounded window: **never extend** an earlier ``valid_until``
    (``min``), and **refuse a close at or before ``valid_from``** (raise, target
    left live) — the latter because an end equal to ``valid_from`` is an empty
    interval and an earlier one is inverted, both of which ``Validity``'s validator
    rejects on the durable store's decode, so the fake must refuse them too rather
    than let a consumer's test pass on a window the production path cannot persist.
    ``now`` must be a guarded, aware-UTC reading.

    Raises:
        MemoryStoreError: If no representable closed window exists at ``now``;
            nothing is written and the target stays live.
    """
    window = target.validity
    end = now if window.valid_until is None else min(now, window.valid_until)
    if window.valid_from is not None and end <= window.valid_from:
        msg = (
            f"cannot retire {target.id!r}: the close instant {end.isoformat()} is not after "
            f"its valid_from {window.valid_from.isoformat()}"
        )
        raise MemoryStoreError(msg)
    return target.model_copy(update={"validity": window.model_copy(update={"valid_until": end})})


def _supersede(incoming: MemoryRecord, new_id: str) -> MemoryRecord:
    """The superseding record: ``incoming`` at a fresh, target-free id (ADR-0045 §4).

    Nothing of the overturned belief is carried across — not its content, its
    provenance, its ``evidence``, nor its ``confidence`` (ADR-0038 §1a). ADR-0045
    §4 stopped rehoming the correction onto the target's id: the target is retained
    with a closed window (:func:`_close_window`) and the correction becomes a *new*
    record at the minted id, written insert-if-absent so a collision is rejected.
    "Carries nothing across, at an id absent from the store" is a complete
    specification, unlike ``_merge``'s fold rule.
    """
    return incoming.model_copy(update={"id": new_id})


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
