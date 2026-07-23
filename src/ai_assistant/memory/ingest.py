"""Ingesting proposed memories: conflict detection, policy, and application.

``MemoryIngestor`` closes the propose/dispose/persist loop. Given a
:class:`~ai_assistant.core.types.MemoryUpdateProposal` (the "propose" half), it:

1. detects conflicting existing memories (same kind, highly similar content),
2. asks the injected :class:`~ai_assistant.core.protocols.MemoryPolicy` to rule
   on the proposal given those conflicts (the "dispose" half), and
3. applies the ruling to the injected
   :class:`~ai_assistant.core.protocols.MemoryStore` (the "persist" half).

It depends only on the store and policy contracts, so it is agnostic to which
concrete store or policy is wired in.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from math import isfinite
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
# as well as in `policy`, deliberately: the policy chooses, but `MemoryIngestor`
# takes rulings from *any* injected `MemoryPolicy`, so the safety property has to
# hold at the boundary that performs the write rather than at the one that
# recommends it.
_SUPERSEDABLE = frozenset({MemorySource.OBSERVED, MemorySource.INFERRED})


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _check_tuning(*, conflict_threshold: float, conflict_limit: int) -> None:
    """Reject conflict tuning that would disable a stage while looking healthy.

    Relocated from ``LearningLoop`` with the values themselves (ADR-0028 §4a),
    so ADR-0022 §4a's guarantee is moved rather than retired: the same values
    are refused at the same moment, by the object that reads them. Each is a
    *silent* misconfiguration, which is why it is refused at construction rather
    than left to surface as behaviour. ``conflict_limit=0`` hands the policy no
    conflicts, so every proposal is ruled on as though nothing contradicted it,
    and a duplicate is accepted while the caller reports a healthy write. A
    ``NaN`` threshold compares ``False`` against every score and does the same.

    Raises:
        TypeError: If ``conflict_limit`` is not an integer, or
            ``conflict_threshold`` is a ``bool``.
        ValueError: If ``conflict_limit`` is below 1, or ``conflict_threshold``
            is not a finite value in ``[0, 1]`` — the range a
            ``MemoryRecord.score`` occupies.
    """
    # `isinstance` rather than a bare `< 1`, which `1.5` and `inf` both survive
    # — and a non-integral limit reaches `MemoryStore.search`, where a store
    # slicing by it raises `TypeError` far from the mistake. `bool` is excluded
    # because it is an `int` subclass and a flag is not a count.
    if isinstance(conflict_limit, bool) or not isinstance(conflict_limit, int):
        msg = f"conflict_limit must be an integer, got {conflict_limit!r}"
        raise TypeError(msg)
    if conflict_limit < 1:
        msg = f"conflict_limit must be at least 1, got {conflict_limit}"
        raise ValueError(msg)
    # Checked before the range test, which a `bool` silently survives: `bool` is
    # an `int` subclass, so `isfinite(True)` holds and `0.0 <= True <= 1.0` is
    # true — a flag would be read as the threshold 1.0, restricting conflicts to
    # perfect-score matches. Rejected for the same reason the limit rejects one.
    if isinstance(conflict_threshold, bool):
        msg = f"conflict_threshold must be a real number, got {conflict_threshold!r}"
        raise TypeError(msg)
    if not isfinite(conflict_threshold) or not 0.0 <= conflict_threshold <= 1.0:
        msg = f"conflict_threshold must be a finite value in [0, 1], got {conflict_threshold!r}"
        raise ValueError(msg)


def _refuse_unsafe_fold(target: MemoryRecord, incoming: MemoryRecord) -> None:
    """Refuse a fold that would destroy data, whichever ruling asks for it.

    Runs before either a ``REINFORCE`` or a ``SUPERSEDE`` arm is selected and is
    keyed on the *records*, not on the relation the ruling names (ADR-0040 §3):
    **every** fold writes at the *target's* id, so the target is always
    overwritten. Two folds are therefore refused outright:

    - **Any fold onto a ``USER_ASSERTED`` target.** Whatever the proposal's
      source, the write replaces what the user told us, and for a non-asserted
      proposal it also downgrades the record's provenance out of the profile.
      ADR-0038 §3 makes this direction absolute: nothing may supersede an
      assertion. §5 is the same rule for a second assertion — no conflict
      heuristic is confident enough to choose between two things the user said.
    - **A ``USER_ASSERTED`` proposal onto an ``EXTERNAL`` target.** The id is
      that system's idempotency key, so the correction inherits it and the next
      routine sync overwrites it, losing the user's words to a background job
      (ADR-0038 §2a).

    ``DefaultMemoryPolicy`` proposes none of these — rule 2 defers, and rule 3
    supersedes only ``OBSERVED``/``INFERRED`` — but a policy reaches the
    ingestor through an injected seam and any conforming implementation may rule
    differently. The refusal therefore lives here, at the boundary that performs
    the write, rather than in the policy that recommends it.

    Checked before either fold is selected, and keyed on the *records* rather
    than on the relation between them. A check gated on "is this a
    supersession?" misses both cases above, since neither is one: they slip into
    the reinforcing merge, which keeps the target's id and destroys it just as
    thoroughly.

    Fail-closed rather than silently downgrading, for the reason that already
    makes an absent fold target raise instead of falling back to storing the
    proposal as new: a write that loses data while reporting success is worse
    than one that stops.

    Raises:
        MemoryStoreError: If the fold is one of the two above.
    """
    if target.provenance.source is MemorySource.USER_ASSERTED:
        msg = (
            f"refusing to supersede {target.id!r}: a {incoming.provenance.source} record may not "
            f"be folded onto a user-asserted one, whose id and content it would replace "
            f"(ADR-0038 §3)"
        )
        raise MemoryStoreError(msg)
    if (
        incoming.provenance.source is MemorySource.USER_ASSERTED
        and target.provenance.source not in _SUPERSEDABLE
    ):
        msg = (
            f"refusing to supersede {target.id!r}: a user assertion may not be folded onto a "
            f"{target.provenance.source} record, whose id it would inherit — only OBSERVED and "
            f"INFERRED beliefs may be superseded (ADR-0038 §2a)"
        )
        raise MemoryStoreError(msg)


def _supersede(target: MemoryRecord, incoming: MemoryRecord) -> MemoryRecord:
    """Replace ``target`` with ``incoming``, keeping only the target's id.

    Nothing of the overturned belief is carried onto the record that overturns
    it — least of all its ``evidence``. ADR-0005 §2 defines that field as
    references *supporting* the record, so unioning the contradicted record's
    evidence into a correction would attach the observations that produced the
    wrong belief as justification for the right one: a fabricated warrant in the
    one field callers use to explain why a memory exists (ADR-0038 §1a).

    A user's assertion is its own warrant and needs no borrowed support, so the
    superseding record is simply ``incoming`` — its provenance is already
    exactly right — rehomed onto the id the stale record occupied. Preserving
    the displaced evidence as *history* is a different thing, and needs the
    representation issue #112 proposes rather than this field.
    """
    return incoming.model_copy(update={"id": target.id})


def _merge(target: MemoryRecord, incoming: MemoryRecord) -> MemoryRecord:
    """Fold ``incoming`` into ``target``, keeping the target's id.

    Newer content wins; evidence is unioned and confidence taken as the maximum,
    so a merge strengthens rather than weakens what is known.

    **Reinforcement only.** Both halves of that — the union and the maximum —
    assume the two records *agree*. Only a ``REINFORCE`` ruling reaches this
    function (ADR-0040 §3): a contradiction is a ``SUPERSEDE``, which
    :meth:`MemoryIngestor._apply` routes to :func:`_supersede` instead.
    """
    provenance = Provenance(
        source=incoming.provenance.source,
        confidence=max(target.provenance.confidence, incoming.provenance.confidence),
        evidence=list(dict.fromkeys([*target.provenance.evidence, *incoming.provenance.evidence])),
        last_updated=incoming.provenance.last_updated,
    )
    return incoming.model_copy(update={"id": target.id, "provenance": provenance})


class MemoryIngestor:
    """Runs a proposed memory through conflict detection, policy, and storage.

    Structurally satisfies :class:`~ai_assistant.core.protocols.MemoryWriter`
    (ADR-0028 §2), which is how `orchestration` reaches this write path without
    importing it.
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
        """Initialise the ingestor.

        Args:
            store: Where accepted memories are persisted and conflicts sought.
            policy: The deterministic policy that rules on each proposal.
            conflict_threshold: Minimum retrieval score for an existing record to
                count as conflicting with the proposal.
            conflict_limit: Maximum number of conflict candidates to consider.
            now: Clock used to stamp expiry on temporary stores; injectable for
                deterministic tests. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, which is what
                protects :meth:`_expiry`'s ``model_copy(update=...)`` write —
                that write skips validators, so the producer is the only place
                left to catch a non-conforming reading (ADR-0026 §2).

        Raises:
            TypeError: If ``conflict_limit`` is not an integer, or
                ``conflict_threshold`` is a ``bool`` (see :func:`_check_tuning`).
            ValueError: If ``conflict_limit`` is below 1, or
                ``conflict_threshold`` is not a finite value in ``[0, 1]`` (see
                :func:`_check_tuning`).
        """
        _check_tuning(conflict_threshold=conflict_threshold, conflict_limit=conflict_limit)
        self._store = store
        self._policy = policy
        self._conflict_threshold = conflict_threshold
        self._conflict_limit = conflict_limit
        self._clock = checked_clock(now, owner="MemoryIngestor")
        # Guards the read-modify-write in `ingest` (issue #248). Constructed
        # here rather than lazily because since Python 3.10 an `asyncio.Lock`
        # binds no loop until it is first awaited, so an ingestor may be built
        # before the loop exists.
        #
        # One lock for all proposals, deliberately. The finest key that would
        # still be *correct* is the proposal's `MemoryKind`, since
        # `_detect_conflicts` searches within one kind and `_apply` refuses a
        # target outside the conflicts, so two proposals of different kinds can
        # never contend for a record. It is rejected on cost, not correctness:
        # it buys concurrency between kinds that nothing has asked for, on a
        # section whose only awaits are two store calls and a deterministic
        # policy, and it pays by making the safety property depend on conflict
        # detection staying kind-scoped — a coupling a later cross-kind
        # conflict rule would break silently, which is the failure mode this
        # change exists to remove.
        self._lock = asyncio.Lock()

    async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        """Detect conflicts, apply the policy, and persist the outcome.

        The three steps are one **read-modify-write**: a fold (``REINFORCE`` or
        ``SUPERSEDE``) folds the proposal into a conflict snapshot taken by the
        search above it, and writes the result back at that record's id.
        Interleaved, two ingests both snapshot the same target before either
        writes, and the second ``add`` silently discards the first — with both
        callers handed a healthy result. Since ADR-0038 the discarded write may
        be a user correction, so the whole sequence is serialised on a lock held
        by this ingestor.

        What that does **not** cover, stated plainly because the guarantee is
        narrower than "ingestion is safe":

        - **Only this ingestor.** Two ``MemoryIngestor`` instances over one
          store hold two different locks and race exactly as before.
        - **Only this process.** An in-process lock says nothing about two
          processes sharing a store file. Closing that needs a compare-and-swap
          on the store itself — a ``MemoryStore`` contract change, tracked as
          issue #104 with issue #248.

        The lock spans the injected policy's ``decide`` as well, because the
        ruling is what the write is derived from; a policy that blocks on I/O
        therefore blocks other ingests. That is the cost of the guarantee, not
        an oversight.

        Args:
            proposal: The memory update to rule on and persist.

        Returns:
            The policy's decision and the id written, if anything was written.
        """
        async with self._lock:
            return await self._ingest(proposal)

    async def _ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        conflicts = await self._detect_conflicts(proposal.proposed)
        proposal = proposal.model_copy(update={"conflicts": [record.id for record in conflicts]})
        decision = await self._policy.decide(proposal, conflicts=conflicts)
        record_id = await self._apply(decision, proposal.proposed, conflicts)
        return MemoryIngestResult(decision=decision, record_id=record_id)

    async def _detect_conflicts(self, record: MemoryRecord) -> list[MemoryRecord]:
        # Over-fetch by one, because the store applies the limit before this
        # method can drop the proposal's own record: a re-proposal would
        # otherwise spend a slot on a record that is then discarded, hiding a
        # genuine conflict ranked just below it. One extra suffices — ids are
        # unique in a store, so at most one match can be the proposal itself.
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
                expires_at = self._expiry(decision.ttl)
                return await self._store.add(proposed.model_copy(update={"expires_at": expires_at}))
            case MemoryDecisionKind.REINFORCE | MemoryDecisionKind.SUPERSEDE:
                target = next((c for c in conflicts if c.id == decision.target_id), None)
                if target is None:
                    # A fold naming an absent target must fail loudly: silently
                    # storing the proposal as new would create the duplicate the
                    # fold was meant to prevent, while reporting success.
                    msg = f"fold target {decision.target_id!r} is not among the conflicts"
                    raise MemoryStoreError(msg)
                _refuse_unsafe_fold(target, proposed)
                # Past the refusal, only a recoverable belief can be overwritten.
                # The ruling names the relation, so the ingestor no longer reads
                # provenance to recover it (ADR-0040 §3): SUPERSEDE overturns the
                # target and carries nothing across, REINFORCE folds the two.
                if decision.kind is MemoryDecisionKind.SUPERSEDE:
                    return await self._store.add(_supersede(target, proposed))
                return await self._store.add(_merge(target, proposed))
            case _:  # REJECT, ASK_USER — nothing is written.
                return None

    def _now_utc(self) -> datetime:
        """The guarded clock's reading, as `memory`'s own error (ADR-0026 §4).

        Load-bearing for :meth:`_expiry`. ``model_copy(update=...)`` does **not**
        re-run validators, so an ``expires_at`` installed that way reaches the
        store exactly as this method left it — and since ADR-0023 makes
        ``MemoryBase.expires_at`` *reject* a naive value rather than assume UTC,
        there is no validator downstream that would have caught it. The guard at
        the producer is therefore the whole protection on this path.

        This replaces the ADR-0023 §6 shim that stood here, and the module-local
        canonicaliser it carried (#169). ADR-0030 §4 permits exactly one
        implementation of that test, in ``core``; routing this write through
        :func:`~ai_assistant.core.clock.checked_clock` is what discharges the
        exception the shim held open.

        Raises:
            MemoryStoreError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise MemoryStoreError(str(exc)) from exc

    def _expiry(self, ttl: timedelta | None) -> datetime | None:
        """Stamp an expiry ``ttl`` from now, failing loudly if it is unrepresentable."""
        if ttl is None:
            return None
        try:
            return self._now_utc() + ttl
        except OverflowError as exc:
            msg = f"temporary-store ttl {ttl!r} overflows the representable date range"
            raise MemoryStoreError(msg) from exc
