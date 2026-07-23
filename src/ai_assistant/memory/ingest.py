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
import uuid
from datetime import UTC, datetime, timedelta
from math import isfinite
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

#: How many times supersession re-mints a colliding id before giving up. A minted
#: id (``uuid4``) collides with vanishing probability, so a handful of attempts is
#: already far past any real collision; the bound exists to make a *pathological*
#: id factory (one that always collides) fail loudly rather than spin (ADR-0045 §4).
_MAX_SUPERSEDE_ATTEMPTS = 5


def _uuid() -> str:
    return str(uuid.uuid4())


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


def _refuse_unsafe_fold(
    target: MemoryRecord, incoming: MemoryRecord, kind: MemoryDecisionKind
) -> None:
    """Refuse a fold that would destroy data, gated on the ruling where it must be.

    Runs before either a ``REINFORCE`` or a ``SUPERSEDE`` arm is selected. Two
    folds are refused; they differ in whether the ruling matters, because
    ADR-0045 §4 made only ``SUPERSEDE`` mint a new id while ``REINFORCE`` still
    folds at the *target's* id:

    - **Clause 1 — any fold onto a ``USER_ASSERTED`` target.** Kept **record-keyed
      for both rulings** (ADR-0045 §5). A window-closing ``SUPERSEDE`` no longer
      *destroys* the assertion, but the conflict signal is topical similarity, not
      contradiction (ADR-0038 §5), and is too weak to retire a record the user
      gave us — a justification the window does not touch. So nothing, of any
      source, under either ruling, may fold onto an assertion.
    - **Clause 2 — a ``USER_ASSERTED`` proposal onto an ``EXTERNAL`` target,
      ``REINFORCE`` only.** The external id is that system's idempotency key. A
      ``REINFORCE`` still inherits it, so the correction is overwritten by the next
      routine sync (ADR-0038 §2a) — the refusal stays. A ``SUPERSEDE`` now gets a
      *fresh* id (ADR-0045 §4), so that hazard is gone and an ``EXTERNAL``
      supersession is permitted at the writer boundary (ADR-0045 §5b). The arm is
      therefore **narrowed to ``REINFORCE``**, not removed.

    ``DefaultMemoryPolicy`` proposes none of these — rule 2 defers, and rule 3
    supersedes only ``OBSERVED``/``INFERRED`` — but a policy reaches the
    ingestor through an injected seam and any conforming implementation may rule
    differently. The refusal therefore lives here, at the boundary that performs
    the write, rather than in the policy that recommends it.

    Fail-closed rather than silently downgrading, for the reason that already
    makes an absent fold target raise instead of falling back to storing the
    proposal as new: a write that loses data while reporting success is worse
    than one that stops.

    Raises:
        MemoryStoreError: If the fold is one of the two above.
    """
    if target.provenance.source is MemorySource.USER_ASSERTED:
        msg = (
            f"refusing to fold onto {target.id!r}: a {incoming.provenance.source} record may not "
            f"be folded onto a user-asserted one, whose belief it would overwrite "
            f"(ADR-0038 §3, ADR-0045 §5)"
        )
        raise MemoryStoreError(msg)
    if (
        kind is MemoryDecisionKind.REINFORCE
        and incoming.provenance.source is MemorySource.USER_ASSERTED
        and target.provenance.source not in _SUPERSEDABLE
    ):
        msg = (
            f"refusing to reinforce {target.id!r}: a user assertion may not be reinforced onto a "
            f"{target.provenance.source} record, whose id it would inherit and the next sync "
            f"overwrite — only OBSERVED and INFERRED beliefs may be reinforced this way "
            f"(ADR-0038 §2a, narrowed to REINFORCE by ADR-0045 §5b)"
        )
        raise MemoryStoreError(msg)


def _checked_id(id_factory: Callable[[], str], *, owner: str) -> str:
    """Read the injected id factory, guarding its output like the clock (ADR-0045 §4).

    Mirrors :func:`~ai_assistant.core.clock.checked_clock`: the minted id is
    installed with ``model_copy(update=...)``, which skips validators, so a
    ``None``, non-``str`` or empty reading would otherwise reach the store
    unchecked — and the two writers would diverge, the in-memory fake storing
    under a bad key while SQLite rejects it (the exact "consumer test passes on
    state the production writer refuses" trap ADR-0045 §4 names). The factory's
    own raising is caught and re-raised as ``MemoryStoreError`` too, so a
    malformed factory fails the write loudly rather than propagating an arbitrary
    exception across the writer seam (ADR-0028 §5).

    Raises:
        MemoryStoreError: If the factory raises, or returns a non-``str`` or empty
            id — before any write is attempted.
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

    The target stays on disk — retained, off the read path — with its window's
    open end brought in to ``now``. ``valid_from`` and every other field are
    preserved; only ``valid_until`` moves. Written with ``model_copy(update=...)``,
    which **skips** ``Validity``'s ``valid_until > valid_from`` validator, so this
    function does that validation itself before handing the value on — the same
    reason the injected clock and id are guarded at the producer.

    Two robustness rules, because a producer *may* set a bounded window (ADR-0045
    §6) that the common open-window case never exercises:

    - **Never extend.** If the target already self-closes at or before ``now``,
      keep that earlier end (``min``): retirement only ever takes a belief *off*
      the read path, never puts one back on or prolongs it.
    - **Refuse an inverted close.** If the chosen end is not after ``valid_from``
      (reachable only when a producer set a future ``valid_from`` and the writer's
      and store's clocks skew, since a conflict search returns only records live at
      store-now), there is no valid closed window at ``now``; raise so the target
      is left live rather than persist an interval ``Validity`` would reject.

    ``now`` must already be a guarded, aware-UTC reading (the ingestor's
    :meth:`MemoryIngestor._now_utc`).

    Raises:
        MemoryStoreError: If no valid closed window exists at ``now`` (the
            inverted-close case above); nothing is written and the target stays live.
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

    Nothing of the overturned belief is carried onto the record that overturns
    it — least of all its ``evidence``. ADR-0005 §2 defines that field as
    references *supporting* the record, so unioning the contradicted record's
    evidence into a correction would attach the observations that produced the
    wrong belief as justification for the right one: a fabricated warrant in the
    one field callers use to explain why a memory exists (ADR-0038 §1a).

    A user's assertion is its own warrant and needs no borrowed support, so the
    superseding record is simply ``incoming`` — its provenance is already exactly
    right — written at a **freshly-minted** id, not the target's. ADR-0045 §4
    stopped rehoming the correction onto the stale id: the target is retained with
    a closed window (:func:`_close_window`) and the correction becomes a *new*
    record. The id is also not ``incoming.id`` — that is caller-supplied and could
    name an unrelated live record — but the minted id, which is written
    insert-if-absent so a collision is rejected, not clobbered.
    """
    return incoming.model_copy(update={"id": new_id})


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
        """Initialise the ingestor.

        Args:
            store: Where accepted memories are persisted and conflicts sought.
            policy: The deterministic policy that rules on each proposal.
            conflict_threshold: Minimum retrieval score for an existing record to
                count as conflicting with the proposal.
            conflict_limit: Maximum number of conflict candidates to consider.
            now: Clock used to stamp expiry on temporary stores and to close a
                superseded target's window; injectable for deterministic tests.
                Guarded by :func:`~ai_assistant.core.clock.checked_clock`, which is
                what protects :meth:`_expiry`'s and :meth:`_apply_supersede`'s
                ``model_copy(update=...)`` writes — those skip validators, so the
                producer is the only place left to catch a non-conforming reading
                (ADR-0026 §2).
            id_factory: Mints the fresh id a ``SUPERSEDE`` writes its correction at
                (ADR-0045 §4); injectable so tests assert exact ids, mirroring the
                clock and ADR-0022 §5's goal-id factory. Guarded at its output by
                :func:`_checked_id`, for the same reason the clock is: the id is
                installed with ``model_copy(update=...)``, so a non-``str`` or empty
                reading would reach the store unchecked. Defaults to random UUIDs.

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
        self._id_factory = id_factory
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
                _refuse_unsafe_fold(target, proposed, decision.kind)
                # Past the refusal, the ruling names the relation, so the ingestor
                # no longer reads provenance to recover it (ADR-0040 §3): SUPERSEDE
                # retires the target (window-close) and writes the correction as a
                # new record, REINFORCE folds the two at the target's id.
                if decision.kind is MemoryDecisionKind.SUPERSEDE:
                    return await self._apply_supersede(target, proposed)
                return await self._store.add(_merge(target, proposed))
            case _:  # REJECT, ASK_USER — nothing is written.
                return None

    async def _apply_supersede(self, target: MemoryRecord, proposed: MemoryRecord) -> str:
        """Close ``target``'s window and write ``proposed`` as a new record (ADR-0045 §4).

        The two writes are one atomic batch — ``[UPSERT(T_closed),
        INSERT_IF_ABSENT(P_new)]`` — via :meth:`MemoryStore.write_atomic` (ADR-0046),
        so a failure between them cannot leave the target retired with no live
        replacement (the regression ADR-0045 §8 refused to ship). The correction's
        id is minted by the guarded id factory and written insert-if-absent, so a
        collision with any stored record — the retained target included — is
        *rejected*, not clobbered; on the resulting
        :class:`~ai_assistant.core.errors.MemoryStoreConflictError` the applier
        re-mints and retries, bounded by :data:`_MAX_SUPERSEDE_ATTEMPTS`. Any other
        ``MemoryStoreError`` aborts with the target left **live and unchanged**,
        because the atomic batch rolls the window-close back with it.

        Returns:
            The **live** record's id — the correction's freshly-minted id, not the
            target's (ADR-0045 §4).

        Raises:
            MemoryStoreError: If the id factory is malformed (:func:`_checked_id`),
                if the bounded re-mint cannot find a free id, or on any other store
                failure — in every case the target is left live and unchanged.
        """
        closed_target = _close_window(target, self._now_utc())
        last_conflict: MemoryStoreConflictError | None = None
        for _ in range(_MAX_SUPERSEDE_ATTEMPTS):
            new_id = _checked_id(self._id_factory, owner="MemoryIngestor")
            if new_id == target.id:
                # The minted id names the retained target itself — a *stored* id, so
                # it must be re-minted (ADR-0045 §4: the absent-id obligation covers
                # "the retained target T included"). Writing it would make the batch
                # two writes to one id, which `write_atomic` rejects as a hard
                # `MemoryStoreError` (repeated id, ADR-0046 §3) rather than the
                # retryable conflict this is, aborting a re-mint the ADR requires.
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
