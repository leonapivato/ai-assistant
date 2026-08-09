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
(§5b); since ADR-0079 §3, that a ``SUPERSEDE`` retires the **whole** ruled-on
supersedable set and that exceeding the writer's conflict ceiling **refuses**
rather than truncating; since ADR-0080 §7, that a retirement **clamps** a
producer-set end rather than extending it and refuses an unrepresentable close;
since ADR-0077 §5, that a ``DERIVED`` proposal citing a record the store does
not hold is refused; and since ADR-0081 §1, that no ruling **installs** the
proposal at an id the proposal itself cites — a ``SUPERSEDE`` re-minting past such
an id rather than refusing. Its conflict heuristic, the *value* of its ceiling, its clock
and how a ``REINFORCE`` combines content and confidence are deliberately *not* —
those are ``MemoryIngestor``'s tuning and `memory`'s semantics, and a fake that
promised them would be a second copy of one implementation.

Beyond the contract it records every proposal it was handed on :attr:`calls`, so
a test can assert what its subject actually delegated.
"""

from __future__ import annotations

import asyncio
import unicodedata
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, assert_never

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    FoldOntoCitedRecordError,
    MemoryStoreConflictError,
    MemoryStoreError,
    SelfConsumingWriteError,
    UnresolvedEvidenceError,
)
from ai_assistant.core.types import (
    MAX_EVIDENCE_CITATIONS,
    BeliefBand,
    DataTier,
    MemoryDecisionKind,
    MemoryIngestResult,
    MemoryKind,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Provenance,
    Validity,
    band_of,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore
    from ai_assistant.core.types import (
        MemoryDecision,
        MemoryRecord,
        MemoryUpdateProposal,
        ReadCoverage,
        SourceReading,
    )

_DEFAULT_CONFLICT_THRESHOLD = 0.75

#: The ceiling on the conflicts one ingest resolves (ADR-0079 §1), matching
#: ``MemoryIngestor``'s default. Duplicated rather than imported, like every other
#: behaviour this fake owes: the two writers must agree about whether a write is
#: *possible*, which "is not tuning under any reading".
_DEFAULT_CONFLICT_LIMIT = 100

#: Bound on the supersession re-mint loop, matching ``MemoryIngestor`` (ADR-0045
#: §4). Duplicated rather than imported: the fake must not reach into `memory`.
_MAX_SUPERSEDE_ATTEMPTS = 5


def _uuid() -> str:
    return str(uuid.uuid4())


# --- two classes, because one constant answered two questions (ADR-0092 §5) ---
# Until ADR-0092 these were a single `_SUPERSEDABLE` frozenset here as in
# `MemoryIngestor`, and they were the same set only by coincidence. §4 breaks it:
# widening one identifier would make the reinforce refusal below stop firing for an
# `EXTERNAL` target, and a *fake* that stopped refusing would be worse than the
# production slip — it would certify consumers a real writer rejects (ADR-0026 §7),
# which is the failure ADR-0079 §3 promoted the retirement set into the contract to
# prevent. Both are held here rather than imported from `memory`, so the fake stays
# free of the subsystem's internals (golden rule 1) while honouring the same
# refusals the production writer does (ADR-0040 §5b).

#: The **retirement class** — beliefs a correction is warranted to retire, used by
#: :func:`_retirement_set` (ADR-0050 §1, ADR-0079 §3, widened with ``EXTERNAL`` by
#: ADR-0092 §4). Matches ``MemoryIngestor``'s.
_RETIREMENT_CLASS = frozenset({MemorySource.OBSERVED, MemorySource.INFERRED, MemorySource.EXTERNAL})

#: The **reinforce-safe class** — targets a user assertion may fold onto *at the
#: target's id*, used by :func:`_refuse_unsafe_fold`'s ``REINFORCE`` arm.
#: ``{OBSERVED, INFERRED, USER_ASSERTED}`` since ADR-0121 §5: membership means "does
#: not carry a foreign idempotency key", which a record the user gave us satisfies
#: and ``EXTERNAL`` does not, however wide the retirement class gets (ADR-0038 §2a,
#: ADR-0045 §5b, ADR-0092 §5). ``USER_ASSERTED`` was outside it only because clause
#: 1 already refused every fold onto such a target, so this question never arose for
#: it; ADR-0121's agreeing exception makes the question live. Not to be merged back
#: into the set above — the two now differ in *both* directions.
_REINFORCE_SAFE = frozenset(
    {MemorySource.OBSERVED, MemorySource.INFERRED, MemorySource.USER_ASSERTED}
)

#: The rulings that dispatch a write, and therefore the ones check 0 gates
#: (:func:`_refuse_secret_write`, ADR-0078 §5b). Derived as a complement rather
#: than listed, so a sixth write-producing ruling joins the gate rather than
#: slipping past a list nobody updated. Duplicated from ``MemoryIngestor``.
_WRITE_PRODUCING_KINDS = frozenset(MemoryDecisionKind) - {
    MemoryDecisionKind.ASK_USER,
    MemoryDecisionKind.REJECT,
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


#: How many attested beliefs one absence-reconciliation page enumerates
#: (ADR-0110 §6). Mirrors ``memory/ingest.py``'s constant; tuning, not contract.
_ABSENCE_PAGE = 50


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
            conflict_limit: The **ceiling** on the conflicts one ingest resolves
                (ADR-0079 §1) — at or below it the whole detected set reaches the
                policy, above it the ingest refuses. Injectable so a consumer's
                test (and the shared suite's resolve-or-refuse obligation) can make
                that boundary observable without planting a hundred records.
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
        # Mirrors `MemoryIngestor`'s lock (#262). A fake that skipped it would let
        # `ingest_reading` claim ADR-0115 §3's guarantee without providing it, and a
        # conformance suite cannot tell the difference — so the fake provides it.
        self._lock = asyncio.Lock()
        self.calls: list[MemoryUpdateProposal] = []

    async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        """Record the proposal, then resolve, rule and apply.

        The caller's proposal is observed exactly once, on the coroutine's first
        executed line, and everything below — the conflict search, what the policy
        is handed, and what is written — reads only that copy (``core.protocols``'
        input clause, ADR-0065). ``MemoryIngestor`` does the same, and a fake that
        did not would let a consumer's test pass on a desync the production writer
        refuses: conflicting beliefs retired over content that was never stored.

        Two copies, not one. :attr:`calls` is public and a consumer's test may
        mutate what it reads there, so the call log gets its own; the working
        snapshot stays private to this call.

        The five refusals ``MemoryIngestor`` carries are carried here too, in the
        same order and for the same reason the fold refusals already are — a fake
        that stored what production refuses lets a consumer's test pass on state the
        real writer would never produce. Unresolvable ``DERIVED`` evidence
        (ADR-0077 §5) fires first, before detection and before the policy; a
        conflict set above the ceiling (ADR-0079 §1) fires in detection, before any
        ruling; a write-producing ruling on secret-tier data (ADR-0078 §5b check 0)
        and a ruling that would install the proposal at an id it cites (ADR-0081 §1)
        both fire between the ruling and the write dispatch; and an unrepresentable
        window close (ADR-0080 §3) fires in the applier, before the atomic batch.

        Raises:
            UnresolvedEvidenceError: If a ``DERIVED`` proposal cites a record the
                store does not hold; nothing is written and the policy is not asked.
            MemoryStoreError: If conflict resolution surfaces more conflicts than
                this writer resolves in one ingest, if a write-producing ruling
                landed on a ``DataTier.SECRET`` proposal, if a ruling would install
                the proposal at an id it cites, if a fold onto a ``USER_ASSERTED``
                target is not covered by a confirmation, if a retirement's window
                cannot be closed, or on any other store or applier failure.
        """
        observed = proposal.model_copy(deep=True)
        return await self._locked_ingest(observed)

    async def _ingest(self, observed: MemoryUpdateProposal) -> MemoryIngestResult:
        """Resolve, rule and apply one already-observed proposal, without the lock.

        Split out of :meth:`ingest` so :meth:`ingest_reading` can drive it inside a
        hold it already owns — the same shape ``MemoryIngestor`` uses, and for the
        same reason: ``asyncio.Lock`` is not reentrant, so the covered path cannot
        call the locking entry point per proposal.
        """
        self.calls.append(observed.model_copy(deep=True))
        await self._require_resolvable_evidence(observed.proposed)
        conflicts = await self._conflicts_for(observed.proposed)
        resolved = tuple(record.id for record in conflicts)
        # Shallow is right here: it copies this writer's own snapshot, whose
        # ``proposed`` no caller holds a reference to. ``observed`` is deliberately
        # kept rather than rebound: its ``conflicts`` are the frozen ids the question
        # was asked about, which is the set ADR-0078 §5b check 4 recomputes the
        # ``question_key`` from — comparing against the live set would refuse every
        # honest answer.
        ruled = observed.model_copy(update={"conflicts": resolved})
        decision = await self._policy.decide(ruled, conflicts=conflicts)
        _refuse_secret_write(decision, observed)
        _refuse_self_consuming_write(decision, observed, resolved=resolved)
        record_id = await self._apply(decision, observed, conflicts, resolved=resolved)
        # The resolved ids come back on **every** ruling (ADR-0078 §4), exactly as
        # they do from ``MemoryIngestor``: a fake that dropped them would let a
        # consumer's test pass while the real writer's caller enqueues a question
        # showing the user no conflicting assertion at all.
        return MemoryIngestResult(decision=decision, record_id=record_id, conflicts=resolved)

    async def ingest_reading(self, reading: SourceReading) -> Sequence[MemoryIngestResult]:
        """Ingest one reading's proposals, then close what its coverage warrants.

        ADR-0115 §1's member, mirroring ``MemoryIngestor.ingest_reading`` so that
        every consumer sees the same behaviour behind the Protocol. It holds this
        fake's own lock across the covered path — the ingest, the selection and the
        closes as one sequence (§3) — because a fake that only *claimed* the
        guarantee would satisfy the shared suite while giving a consumer a subject
        whose isolation is imaginary, which is the failure a canonical fake exists to
        prevent rather than to model.

        Args:
            reading: Observed whole before the first ``await`` (ADR-0065, §6).

        Returns:
            One result per proposal, in the reading's own order (§1).

        Raises:
            MemoryStoreError: As :meth:`ingest` raises, or as a close raises for an
                unrepresentable window. Nothing is caught or converted.
            UnresolvedEvidenceError: As :meth:`ingest` raises.
        """
        observed = reading.model_copy(deep=True)
        if observed.coverage is None:
            return [await self._locked_ingest(proposal) for proposal in observed.proposals]
        async with self._lock:
            results = [await self._ingest(proposal) for proposal in observed.proposals]
            await self._close_absent(
                source=observed.source, coverage=observed.coverage, results=results
            )
            return results

    async def _locked_ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        """One proposal under the ordinary per-proposal hold."""
        async with self._lock:
            return await self._ingest(proposal)

    async def _close_absent(
        self,
        *,
        source: str,
        coverage: ReadCoverage,
        results: Sequence[MemoryIngestResult],
    ) -> int:
        """ADR-0110 §3's closes, called only with :attr:`_lock` held.

        §4's suspension clause first: where any proposal stored nothing — a
        ``REJECT``, or an ``ASK_USER`` deferral — the reading warrants no absence at
        all, because the entry *is* in the source and the ingest simply stored
        nothing for it. Keyed on ``record_id`` being ``None`` rather than on a
        remembered list of rulings, so a ruling added later lands on the right side.
        """
        if any(result.record_id is None for result in results):
            return 0
        present = {result.record_id for result in results}
        now = self._now_utc()
        closes = [
            MemoryWrite(record=_close_window(record, now), mode=MemoryWriteMode.UPSERT)
            for record in await self._absence_candidates(
                source=source, coverage=coverage, present=present
            )
        ]
        if not closes:
            return 0
        await self._store.write_atomic(closes)
        return len(closes)

    async def _absence_candidates(
        self,
        *,
        source: str,
        coverage: ReadCoverage,
        present: set[str | None],
    ) -> list[MemoryRecord]:
        """The live records ADR-0110 §3's four conditions make demotable.

        Condition 3 is evaluated against the **extent the record's attestation
        declares**, as ADR-0117 §3 reads it, and never against the record's
        envelope validity window. The rule is duplicated from ``MemoryIngestor``
        rather than imported (golden rule 1), so ADR-0117 §3's normative clause
        binds the two together: a fake still demoting on the envelope window while
        the real writer demoted on the extent would drive the shared suite through
        two different rules while reporting one.
        """
        candidates: list[MemoryRecord] = []
        offset = 0
        while True:
            page = await self._store.list_beliefs(
                bands=[BeliefBand.ATTESTED], limit=_ABSENCE_PAGE, offset=offset
            )
            for record in page:
                attestation = record.provenance.attestation
                if attestation is None or attestation.reported_by != source:
                    continue  # §3 condition 1.
                if record.id in present:
                    continue  # §3 condition 4.
                extent = attestation.extent
                # §3 condition 3, over the source's own statement of where the
                # entry lies (ADR-0117 §3). No extent, no demotion.
                if extent is not None and coverage.contains(extent):
                    candidates.append(record)  # §3 conditions 2 and 3.
            if len(page) < _ABSENCE_PAGE:
                return candidates
            offset += _ABSENCE_PAGE

    async def _require_resolvable_evidence(self, record: MemoryRecord) -> None:
        """Refuse a ``DERIVED`` proposal citing a record the store does not hold.

        ADR-0077 §5's write-time resolvability floor, duplicated from
        ``MemoryIngestor`` rather than imported (golden rule 1). Scoped to the
        ``DERIVED`` band, and deliberately not a floor on citing *nothing* — an
        empty tuple names no record that fails to resolve, so it passes here and is
        the policy's to judge. Every unresolved id is named, in citation order, so
        a consumer's stage can compare them against the batch it selected and tell
        an evidence race from a producer bug.

        Raises:
            UnresolvedEvidenceError: If any cited id names no record the store
                returns; nothing is written and no ruling is sought.
        """
        if band_of(record.provenance.source) is not BeliefBand.DERIVED:
            return
        unresolved: list[str] = []
        for cited in dict.fromkeys(record.provenance.evidence):
            if await self._store.get(cited) is None:
                unresolved.append(cited)
        if unresolved:
            msg = (
                f"refusing to ingest {record.id!r}: its {record.provenance.source} provenance "
                f"cites {len(unresolved)} record(s) this store does not hold — "
                f"{', '.join(repr(cited) for cited in unresolved)} (ADR-0077 §5)"
            )
            raise UnresolvedEvidenceError(msg, unresolved)

    async def _conflicts_for(self, record: MemoryRecord) -> list[MemoryRecord]:
        """Every conflict retrieval surfaced, or a refusal above the ceiling.

        ``conflict_limit`` is a ceiling rather than a truncation budget (ADR-0079
        §1), so nothing detected is discarded before the policy and an over-ceiling
        ingest refuses with nothing written and no ruling sought. The two rows of
        headroom are the standing over-fetch for the proposal's own record plus
        ADR-0079 §1's overflow probe, without which "exactly the ceiling" and "more
        than the ceiling" are indistinguishable. Mirrors ``MemoryIngestor``.

        Raises:
            MemoryStoreError: If retrieval surfaced more conflicts than this writer
                will resolve in one ingest.
        """
        matches = await self._store.search(
            record.content,
            limit=self._conflict_limit + 2,
            kinds=[MemoryKind(record.kind)],
        )
        conflicts = [
            match
            for match in matches
            if match.id != record.id and (match.score or 0.0) >= self._conflict_threshold
        ]
        if len(conflicts) > self._conflict_limit:
            msg = (
                f"refusing to ingest {record.id!r}: conflict resolution surfaced more than "
                f"{self._conflict_limit} conflicting records, more than one ingest resolves. "
                f"Nothing was written and no ruling was sought — a correction resolves every "
                f"conflict it is shown, or it does not land (ADR-0079 §1)"
            )
            raise MemoryStoreError(msg)
        return conflicts

    async def _apply(
        self,
        decision: MemoryDecision,
        proposal: MemoryUpdateProposal,
        conflicts: list[MemoryRecord],
        *,
        resolved: tuple[str, ...],
    ) -> str | None:
        proposed = proposal.proposed
        # Every installing arm passes through `_installed` (ADR-0086 §2), so the
        # bound is a property of the seam rather than of one ruling. A no-op on a
        # `_merge` result, which has already bounded the union it formed.
        match decision.kind:
            case MemoryDecisionKind.ACCEPT:
                return await self._install(_installed(proposed))
            case MemoryDecisionKind.STORE_TEMPORARY:
                return await self._install(
                    _installed(
                        proposed.model_copy(update={"expires_at": self._expiry(decision.ttl)})
                    )
                )
            case MemoryDecisionKind.REINFORCE | MemoryDecisionKind.SUPERSEDE:
                target = next((c for c in conflicts if c.id == decision.target_id), None)
                if target is None:
                    msg = f"fold target {decision.target_id!r} is not among the conflicts"
                    raise MemoryStoreError(msg)
                _refuse_unsafe_fold(target, proposal, decision.kind, resolved=resolved)
                if decision.kind is MemoryDecisionKind.SUPERSEDE:
                    return await self._apply_supersede(
                        _retirement_set(target, conflicts, proposal=proposal, resolved=resolved),
                        proposed,
                    )
                # The clock reading is taken here, not inside `_merge`: `_now_utc`
                # translates a bad reading into `MemoryStoreError` as the ingestor
                # does, and a module-level helper has no error class to raise.
                return await self._fold(_installed(_merge(target, proposed, now=self._now_utc())))
            case _:  # REJECT, ASK_USER — nothing is written.
                return None

    async def _install(self, record: MemoryRecord) -> str:
        """Write ``record`` as a **new** record, refusing a colliding id.

        Contract behaviour, mirroring ``MemoryIngestor`` (ADR-0108 §2). The ruling
        that reached here is that the proposal contradicts nothing retrieval
        surfaced, so a stored id is an accident in every case and the write is
        refused rather than silently replacing a record no ruling was made about
        (#630). ``INSERT_IF_ABSENT`` buys that check with no read and no race
        (ADR-0108 §1), and the conflict propagates unchanged — the proposal's id is
        the producer's, so re-minting it would edit a record the producer made
        (ADR-0081 §9).

        Raises:
            MemoryStoreConflictError: ``record.id`` already names a stored record.
                Nothing is written.
            MemoryStoreError: Any other store failure. Nothing is written.
        """
        written = await self._store.write_atomic(
            [MemoryWrite(record=record, mode=MemoryWriteMode.INSERT_IF_ABSENT)]
        )
        return written[0]

    async def _fold(self, record: MemoryRecord) -> str:
        """Write ``record`` at the fold target's id, declaring the overwrite.

        Contract behaviour, mirroring ``MemoryIngestor``: ADR-0108 §2's one
        deliberate upsert. ``_merge`` keeps the target's id, and the target is the
        one the ruling named, so landing on a stored record is the decision rather
        than a collision — ADR-0022 §4's protected case, stated instead of
        defaulted.

        Raises:
            MemoryStoreError: The store refused the write. Nothing is written.
        """
        written = await self._store.write_atomic(
            [MemoryWrite(record=record, mode=MemoryWriteMode.UPSERT)]
        )
        return written[0]

    async def _apply_supersede(self, targets: list[MemoryRecord], proposed: MemoryRecord) -> str:
        """Retire the whole set and write ``proposed`` at a fresh id (ADR-0079 §3).

        Contract behaviour, mirroring ``MemoryIngestor``: ``targets`` is the full
        set a ``SUPERSEDE`` retires (:func:`_retirement_set`) — the ruling's named
        target plus every other supersedable conflict — and every window-close plus
        the insert-if-absent of the correction are **one** atomic ``write_atomic``
        batch (ADR-0046, ADR-0045 §8). The correction's id comes from the guarded
        factory and is re-minted on a bounded number of collisions — **including** a
        candidate the proposal cites, which would otherwise leave the correction
        standing as its own warrant (ADR-0081 §4) — and any other store failure
        leaves every target live and unchanged. A fake that retired
        only the named target — which this one did until ADR-0079 §3 promoted the
        set into the contract — would let an `orchestration` test see one retirement
        where production performs N.

        The close instant is sampled **once** for the whole set and every target's
        end computed from it before any write (ADR-0080 §1/§6), so one refusal
        aborts the whole supersession rather than skipping the awkward member.

        Returns:
            The correction's freshly-minted id — the id now holding the live belief.
        """
        now = self._now_utc()
        closed = [_close_window(target, now) for target in targets]
        retired_ids = {target.id for target in targets}
        # ADR-0081 §1's second evaluation point (§2, §4), mirroring
        # ``MemoryIngestor``: a `SUPERSEDE`'s destination does not exist until it is
        # minted, so its candidate is tested here rather than at the seam.
        cited = frozenset(proposed.provenance.evidence)
        last_conflict: MemoryStoreConflictError | None = None
        for _ in range(_MAX_SUPERSEDE_ATTEMPTS):
            new_id = _checked_id(self._id_factory, owner="FakeMemoryWriter")
            if new_id in cited:
                # Installing the correction at an id it cites would leave it standing
                # as its own warrant — reached without replacing anything, since
                # `INSERT_IF_ABSENT` overwrites nothing. A re-mint is free, so it
                # joins the bounded loop rather than refusing (ADR-0081 §4).
                last_conflict = MemoryStoreConflictError(
                    f"minted id {new_id!r} is cited by the proposal's own evidence; re-minting"
                )
                continue
            if new_id in retired_ids:
                # The minted id names one of the retained targets — a stored id that
                # must be re-minted (ADR-0045 §4). Writing it would make the batch
                # two writes to one id, a hard `MemoryStoreError` (ADR-0046 §3), not
                # the retryable conflict this is. Mirrors ``MemoryIngestor``.
                last_conflict = MemoryStoreConflictError(
                    f"minted id {new_id!r} names a superseded target; re-minting"
                )
                continue
            # The retirements are **not** bounded — a window-close is a retirement,
            # not an install, so a legacy over-bound target goes back whole
            # (ADR-0086 §2). The correction is an install and carries the
            # proposal's own count, never the target's (ADR-0086 §4).
            batch = [
                MemoryWrite(record=closed_target, mode=MemoryWriteMode.UPSERT)
                for closed_target in closed
            ]
            batch.append(
                MemoryWrite(
                    record=_installed(_supersede(proposed, new_id)),
                    mode=MemoryWriteMode.INSERT_IF_ABSENT,
                )
            )
            try:
                await self._store.write_atomic(batch)
            except MemoryStoreConflictError as exc:
                last_conflict = exc
                continue
            return new_id
        msg = (
            f"supersession could not mint a free id for a correction to {retired_ids!r} "
            f"after {_MAX_SUPERSEDE_ATTEMPTS} attempts; the targets are left live and unchanged"
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
    target: MemoryRecord,
    proposal: MemoryUpdateProposal,
    kind: MemoryDecisionKind,
    *,
    resolved: tuple[str, ...],
) -> None:
    """Refuse a fold that would destroy data, as ``MemoryIngestor`` does.

    Contract, not tuning (ADR-0040 §5b, as narrowed by ADR-0045 §5 and ADR-0078
    §5b). Two refusals, differing in whether the ruling matters because ADR-0045 §4
    made only ``SUPERSEDE`` mint a new id:

    - **Clause 1 — any fold onto a ``USER_ASSERTED`` target**, under either ruling.
      Kept record-keyed: the conflict signal is too weak to retire a record the
      user gave us, which the window does not change (ADR-0045 §5). **Narrowed by
      two exceptions and no others.** A ``SUPERSEDE`` whose target the proposal's
      ``confirmation`` genuinely covers is permitted, because there the signal is
      the user's own answer (:func:`_confirmation_covers`, ADR-0078 §5b). And an
      **agreeing restatement** is permitted — a ``REINFORCE`` whose incoming record
      is ``USER_ASSERTED`` and which agrees with the target under ADR-0121 §1
      (:func:`_agreeing_restatement`, ADR-0121 §5) — because that fold writes the
      target's own content back at the target's own id and so replaces and retires
      nothing, which is what clause 1's two justifications are both about.
    - **Clause 2 — a ``USER_ASSERTED`` proposal onto an ``EXTERNAL`` target,
      ``REINFORCE`` only.** A ``REINFORCE`` still inherits the external id and is
      overwritten by the next sync (ADR-0038 §2a); a ``SUPERSEDE`` now gets a fresh
      id and is permitted (ADR-0045 §5b), so the arm is narrowed to ``REINFORCE``.
      Keyed on :data:`_REINFORCE_SAFE`, **not** on the retirement class ADR-0092 §4
      widened: reading that class here would turn ``source not in …`` false for an
      ``EXTERNAL`` target and stop this refusal firing (ADR-0092 §5).

    Duplicated from ``MemoryIngestor`` deliberately: the fake owes the same
    refusals but must not reach into the ``memory`` subsystem to get them (golden
    rule 1), so a consumer's test cannot pass on state the production writer would
    have refused.

    Raises:
        MemoryStoreError: If the fold is one of the two above and no covering
            confirmation permits it.
    """
    incoming = proposal.proposed
    if (
        target.provenance.source is MemorySource.USER_ASSERTED
        and not _confirmation_covers(target, proposal, kind, resolved=resolved)
        and not _agreeing_restatement(target, incoming, kind)
    ):
        msg = (
            f"refusing to fold onto {target.id!r}: a {incoming.provenance.source} record may not "
            f"be folded onto a user-asserted one (ADR-0038 §3, ADR-0045 §5, narrowed by "
            f"ADR-0078 §5b and ADR-0121 §5)"
        )
        raise MemoryStoreError(msg)
    if (
        kind is MemoryDecisionKind.REINFORCE
        and incoming.provenance.source is MemorySource.USER_ASSERTED
        and target.provenance.source not in _REINFORCE_SAFE
    ):
        msg = (
            f"refusing to reinforce onto {target.id!r}: a user assertion may not be reinforced "
            f"onto a {target.provenance.source} record whose id it would inherit — only OBSERVED "
            f"and INFERRED beliefs (ADR-0038 §2a, narrowed to REINFORCE by ADR-0045 §5b)"
        )
        raise MemoryStoreError(msg)


def _agreement_form(content: str) -> str:
    """ADR-0121 §1's four transformations, in order, as ``MemoryIngestor`` applies them.

    Unicode NFC normalisation, Unicode case folding, replacement of every maximal
    run of Unicode whitespace by a single space, and removal of leading and trailing
    whitespace — the last two performed together by ``str.split()`` with no
    argument, which splits on *Unicode* whitespace as the clause requires.
    Deliberately no fifth transformation: the result is not re-normalised after
    folding, and nothing stems, expands or strips punctuation.

    Duplicated from ``MemoryIngestor`` rather than imported (golden rule 1), which
    is why ADR-0121 §1 states the predicate normatively instead of leaving one
    implementation to define it: a fake computing a *wider* form would admit folds
    onto a user assertion that the production writer refuses.

    Args:
        content: A record's ``content`` string.

    Returns:
        The comparison form, meaningful only against another string put through
        this same function.
    """
    return " ".join(unicodedata.normalize("NFC", content).casefold().split())


def _agrees(left: MemoryRecord, right: MemoryRecord) -> bool:
    """Whether two records agree under ADR-0121 §1 — ``kind`` and ``content``, nothing else.

    Never a retrieval score, a ``Provenance`` field, a validity window, a band, an
    embedding, or any value from a ``ModelProvider``. Duplicated from
    ``MemoryIngestor`` (golden rule 1).

    Args:
        left: One record.
        right: The other.

    Returns:
        Whether a reader can see that the two say the same thing, without any
        judgement being exercised.
    """
    return left.kind == right.kind and _agreement_form(left.content) == _agreement_form(
        right.content
    )


def _agreeing_restatement(
    target: MemoryRecord, incoming: MemoryRecord, kind: MemoryDecisionKind
) -> bool:
    """Whether clause 1's ADR-0121 §5 exception admits this fold.

    Three conditions: the ruling is ``REINFORCE`` (a ``SUPERSEDE`` onto an assertion
    is untouched by this exception, whatever the records say); the incoming record
    is ``USER_ASSERTED`` (the argument is that the same authority is saying the same
    thing again, and a non-asserted proposal agreeing with an assertion is the case
    ADR-0121 §11 leaves ruling ``ASK_USER``); and the records agree under ADR-0121
    §1.

    **Verified, not trusted from the ruling** (ADR-0121 §5, ADR-0038 §2a), exactly
    as ``MemoryIngestor`` verifies it, and duplicated for the same reason every
    other refusal here is: a fake that admitted the fold on the ruling's say-so
    would certify consumers the production writer rejects (ADR-0026 §7).

    Args:
        target: The stored record the ruling folds into.
        incoming: The proposed record being folded in.
        kind: The ruling being applied.

    Returns:
        Whether the fold is the one ADR-0121 §5 permits.
    """
    return (
        kind is MemoryDecisionKind.REINFORCE
        and incoming.provenance.source is MemorySource.USER_ASSERTED
        and _agrees(target, incoming)
    )


def _confirmation_covers(
    target: MemoryRecord,
    proposal: MemoryUpdateProposal,
    kind: MemoryDecisionKind,
    *,
    resolved: tuple[str, ...],
) -> bool:
    """Whether a confirmation authorises retiring ``target`` (ADR-0078 §5b).

    Clause 1's one exception, with the same five checks ``MemoryIngestor`` performs
    and for the same reason a fake owes every other refusal: the exception is
    **verified, not trusted**, because a gate that opened on an unexamined field
    would hand the writer boundary's guarantee back to the caller's good intentions.
    (Check 0 is not among them: it gates the *write* rather than the fold, so it
    sits between the ruling and the write dispatch —
    :func:`_refuse_secret_write`.)

    1. the ruling is ``SUPERSEDE`` — a ``REINFORCE`` onto an assertion would rewrite
       the user's own words at the target's id, which no answer authorises;
    2. the target id is in ``confirmation.retires``;
    3. the target id is among the conflicts *this* ingest resolved;
    4. ``confirmation.question_key`` equals the key recomputed from the proposal
       **as handed to ``ingest``**, whose ``conflicts`` are the frozen ids the
       question was asked about. This is what stops the value being a bearer token
       a different question's apply could spend;
    5. every id in ``confirmation.retires`` was among those frozen conflicts, so the
       authority is bounded by what the user was *shown* as well as by what is live.

    Duplicated from ``MemoryIngestor`` rather than imported (golden rule 1).

    Returns:
        ``True`` iff all five hold.
    """
    confirmation = proposal.confirmation
    if confirmation is None or kind is not MemoryDecisionKind.SUPERSEDE:
        return False
    frozen = set(proposal.conflicts)
    return (
        target.id in confirmation.retires
        and target.id in resolved
        and confirmation.question_key == proposal.question_key
        and frozen.issuperset(confirmation.retires)
    )


def _refuse_secret_write(decision: MemoryDecision, proposal: MemoryUpdateProposal) -> None:
    """Refuse any *write* of a ``DataTier.SECRET`` proposal (ADR-0078 §5b check 0).

    A refusal at the writer boundary, independent of the model validators, because a
    validator is not a boundary: ``model_construct`` and ``model_copy(update=...)``
    both skip validation, and this repository treats a model tampered past
    ``frozen=True`` as inside its threat model (ADR-0018 §3, ADR-0021 §4). Without
    it every check above can pass on a validator-bypassing secret proposal under an
    injected ``SUPERSEDE`` policy and Tier 0 content lands in the ``MemoryStore`` —
    ADR-0004 §3's "never in the memory database".

    **It gates the write, not the ruling.** It runs after the policy has ruled and
    before any write is dispatched, so it reaches every write-producing ruling and
    no ruling that writes nothing: ``ASK_USER`` and ``REJECT`` return normally,
    which is what preserves the ordinary secret-tier path ADR-0078 §1 keeps.
    Duplicated from ``MemoryIngestor`` (golden rule 1).

    Raises:
        MemoryStoreError: If the ruling would write and the proposal is Tier 0.
    """
    if decision.kind in _WRITE_PRODUCING_KINDS and proposal.sensitivity is DataTier.SECRET:
        msg = (
            f"refusing to write {proposal.proposed.id!r}: a {decision.kind} ruling on secret-tier "
            f"data would put Tier 0 content in the memory database, which lives in the OS keyring "
            f"and never in a database or a committed file (ADR-0004 §3, ADR-0078 §5b)"
        )
        raise MemoryStoreError(msg)


def _installed_at(
    decision: MemoryDecision, proposed: MemoryRecord, *, resolved: tuple[str, ...]
) -> str | None:
    """The id this ruling would **install** the proposal at, as ``MemoryIngestor`` has it.

    A write *installs* when it stores the proposal's content at an id; it *retires*
    when it stores an existing record back with only its window narrowed (ADR-0080
    §1), which lands nothing of the proposal anywhere. ``None`` means this ruling
    installs nothing at an id known at the seam: ``REJECT`` and ``ASK_USER`` write
    nothing; a ``SUPERSEDE``'s destination does not exist until
    :meth:`FakeMemoryWriter._apply_supersede` mints it, so its candidate is tested
    there and a hit re-mints (ADR-0081 §2/§4); and a ``REINFORCE`` naming a target
    outside ``resolved`` has no destination at all, since ADR-0081 §6 draws the
    fold's write id **from the conflicts** — that ruling installs nothing and keeps
    the standing not-among-the-conflicts refusal. ``resolved`` costs no store read:
    it is the tuple :meth:`FakeMemoryWriter.ingest` already computed before the
    policy was asked. Duplicated from ``MemoryIngestor`` rather than imported
    (golden rule 1).
    """
    match decision.kind:
        case MemoryDecisionKind.ACCEPT | MemoryDecisionKind.STORE_TEMPORARY:
            return proposed.id
        case MemoryDecisionKind.REINFORCE:
            # The fold lands at the *target's* id, never at `proposed.id` — and only
            # a target among the resolved conflicts is a destination at all.
            return decision.target_id if decision.target_id in resolved else None
        case MemoryDecisionKind.SUPERSEDE:
            return None
        case MemoryDecisionKind.REJECT | MemoryDecisionKind.ASK_USER:
            return None
    # No `case _`: a new `MemoryDecisionKind` fails the type check here rather than
    # silently acquiring an unguarded write.
    assert_never(decision.kind)


def _refuse_self_consuming_write(
    decision: MemoryDecision, proposal: MemoryUpdateProposal, *, resolved: tuple[str, ...]
) -> None:
    """Refuse a write landing at an id the proposal cites (ADR-0081 §1).

    The fourth obligation on ``MemoryWriter.ingest``, and one a fake owes for
    ADR-0079 §3's reason: a fake that stored a self-standing warrant would let a
    consumer's test pass on state the production writer refuses. It gates the
    **write** rather than the ruling, so it sits between the ruling and the write
    dispatch — the seam :func:`_refuse_secret_write` occupies — and not in
    :func:`_refuse_unsafe_fold`, which ``ACCEPT`` and ``STORE_TEMPORARY`` never
    reach (ADR-0081 §2).

    It reads nothing from the store: its inputs are the observed proposal, the
    ruling, and the conflict ids already resolved before the policy was asked, so
    it is never a race and always a producer fault, which is why it
    raises plain ``MemoryStoreError`` and specifically **not**
    ``UnresolvedEvidenceError`` — the evidence resolves; the write would consume it
    (§3). Scoped to no band (§1b), and quantified over **this proposal's** evidence
    rather than the tuple :func:`_merge` unions (§1a). Duplicated from
    ``MemoryIngestor`` (golden rule 1).

    Args:
        decision: The ruling the policy made.
        proposal: The proposal as this call observed it.
        resolved: The conflict ids this ingest resolved.

    Raises:
        FoldOntoCitedRecordError: If a ``REINFORCE`` would fold onto a record the
            proposal cites — the policy's destination (ADR-0116 §2).
        SelfConsumingWriteError: If an ``ACCEPT`` or ``STORE_TEMPORARY`` would
            install at a cited ``proposed.id`` — the producer's. Both are
            ``MemoryStoreError``; nothing is written and no window is closed. The
            fake raises exactly what the real writer raises, or it would certify a
            consumer the real writer breaks (ADR-0026 §7).
    """
    proposed = proposal.proposed
    destination = _installed_at(decision, proposed, resolved=resolved)
    if destination is not None and destination in proposed.provenance.evidence:
        # Which arm, by **who chose the destination** (ADR-0116 §2). `ACCEPT` and
        # `STORE_TEMPORARY` install at `proposed.id`, minted and cited by the
        # producer, so nothing outside it chose either value and the refusal is the
        # producer bug ADR-0081 §Context describes. `REINFORCE` installs at the
        # ruling's `target_id`, which the *policy* picked by conflict detection over
        # the proposal's own content — unforeseeable to a producer generalising over
        # the records it cites, and the only arm a caller may continue past (§4).
        # The ruling is already in hand here, so the discrimination costs no extra
        # input and no store read, which is the property ADR-0081 §1 protects.
        refusal = (
            FoldOntoCitedRecordError
            if decision.kind is MemoryDecisionKind.REINFORCE
            else SelfConsumingWriteError
        )
        msg = (
            f"refusing to write {proposed.id!r}: a {decision.kind} ruling would install it at "
            f"{destination!r}, an id its own provenance cites as evidence — the belief would "
            f"stand as its own warrant (ADR-0081 §1)"
        )
        raise refusal(msg)


def _checked_id(id_factory: Callable[[], str], *, owner: str) -> str:
    """Read the injected id factory, guarding its output like ``MemoryIngestor``.

    The minted id is installed with ``model_copy(update=...)``, which skips
    validators, so a raising, non-``str`` or empty reading must become a
    ``MemoryStoreError`` *before* the write (ADR-0045 §4). An **exact** ``str`` is
    required (``type(minted) is str``), not merely an ``isinstance`` one: a hostile
    ``str`` subclass — say one whose ``__hash__`` raises — passes ``isinstance`` and
    is then hashed as a store key, leaking an arbitrary exception across the seam.
    Duplicated from the production writer so the fake refuses a malformed factory
    identically.

    Raises:
        MemoryStoreError: If the factory raises, or returns anything that is not a
            non-empty built-in ``str``.
    """
    try:
        minted = id_factory()
    except Exception as exc:  # any factory failure is the store's error, not the caller's
        msg = f"the id factory injected into {owner} raised while minting a supersession id"
        raise MemoryStoreError(msg) from exc
    if type(minted) is not str or not minted:
        # Introspect nothing about the returned object (not ``repr``, not
        # ``type(minted).__name__``): a hostile ``__repr__`` or metaclass
        # ``__getattribute__`` could raise and leak past the guard. Only ``owner``
        # appears. ``type(minted) is not str`` invokes no user code.
        msg = f"the id factory injected into {owner} did not return a non-empty built-in str"
        raise MemoryStoreError(msg)
    return minted


def _retirement_set(
    target: MemoryRecord,
    conflicts: list[MemoryRecord],
    *,
    proposal: MemoryUpdateProposal,
    resolved: tuple[str, ...],
) -> list[MemoryRecord]:
    """The full set of beliefs a ``SUPERSEDE`` retires (ADR-0050 §1, ADR-0079 §3).

    The named ``target`` — whatever its source, so an ``EXTERNAL`` record a policy
    named explicitly *is* retired (ADR-0045 §5b) — plus every other conflict whose
    source is in :data:`_RETIREMENT_CLASS`. ``EXTERNAL`` **siblings are now swept in
    too** (ADR-0092 §4's adoption, partially superseding ADR-0050 §1's hold-out): a
    user's correction retires the import rather than leaving it live beside them.
    ``retires`` stays a ceiling rather than an instruction; what ADR-0092 §4 removed
    is the reason an ``EXTERNAL`` sibling needed a confirmation's authority at all.
    ``USER_ASSERTED`` siblings are never swept in **on similarity**
    (ADR-0045 §5), and are swept in **only** where the proposal's ``confirmation``
    genuinely covers them (ADR-0078 §5b's narrowing of the hold-out) — so a
    confirmation naming two prior assertions retires both in the one batch. Checked
    per record rather than inferred from the named target, because under an injected
    policy a confirmation can arrive naming an *inference* while a live assertion
    sits in ``retires``.

    ``target`` leads; order among the rest follows ``conflicts``, so the batch is
    deterministic. Duplicated from ``MemoryIngestor`` rather than imported (golden
    rule 1), like every other behaviour this fake owes: ADR-0079 §3 promoted the set
    into the ``MemoryWriter`` contract precisely because a fake retiring one record
    where production retires N let a consumer's test pass on state production would
    never produce.
    """
    others = [
        conflict
        for conflict in conflicts
        if conflict.id != target.id
        and (
            conflict.provenance.source in _RETIREMENT_CLASS
            or (
                conflict.provenance.source is MemorySource.USER_ASSERTED
                and _confirmation_covers(
                    conflict, proposal, MemoryDecisionKind.SUPERSEDE, resolved=resolved
                )
            )
        )
    ]
    return [target, *others]


def _close_window(target: MemoryRecord, now: datetime) -> MemoryRecord:
    """Return ``target`` retired at the earlier of ``now`` and its own end (ADR-0080 §1).

    The target is retained off the read path with its window's end brought in to
    ``end = now`` where the window is unbounded at the end, otherwise
    ``end = min(now, valid_until)``; ``valid_from`` and every other field are
    preserved. Mirrors ``_close_window`` in ``memory/ingest.py``, carrying ADR-0080
    §1's clamp — a retirement never widens a window, so it cannot resurrect a
    self-closed belief — and §3's refusal of a close at or before ``valid_from``,
    **the tie included**, which is the empty interval ``[F, F)`` the durable store's
    decode re-validation rejects. Both so the fake cannot pass a consumer's test on
    state the production writer would refuse. ``now`` must be a guarded, aware-UTC
    reading, and it is one instant for the whole retirement set.

    Raises:
        MemoryStoreError: If the chosen end is at or before ``valid_from``; nothing
            is written and every record in the set is unchanged.
    """
    window = target.validity
    end = now if window.valid_until is None else min(now, window.valid_until)
    if window.valid_from is not None and end <= window.valid_from:
        msg = (
            f"cannot retire {target.id!r}: a close at {end.isoformat()} is at or before its "
            f"valid_from {window.valid_from.isoformat()} — an unrepresentable window the store "
            f"would reject (ADR-0080 §3)"
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
    The correction is also given a **fresh open window** (ADR-0045 §4), overriding
    any ``validity`` the proposal carried, so a supersession always leaves a *live*
    belief — a proposal with a producer-set closed or future window must not retire
    the target and leave the correction hidden. "Carries nothing of the target, at a
    fresh id with a fresh open window" is a complete specification, unlike
    ``_merge``'s fold rule.
    """
    return incoming.model_copy(update={"id": new_id, "validity": Validity()})


def _bounded_evidence(evidence: Sequence[str], *, elided: int) -> tuple[tuple[str, ...], int]:
    """ADR-0086 §3's retention rule and §4's recurrence, in one place.

    Duplicated from ``MemoryIngestor`` rather than shared, exactly as this module's
    other contract helpers are: ``ai_assistant.testing`` may not import a subsystem
    (golden rule 1). A fake looser than the contract would certify consumers a real
    writer rejects (ADR-0026 §7), and this rule is contract.

    Keeps the **last** :data:`MAX_EVIDENCE_CITATIONS` entries — the tuple is
    ordered oldest-accumulated first, so the oldest are displaced — and returns the
    elision count to store: the sum over the install's sources, plus what it
    displaced. An upper bound, never a total (ADR-0086 §4).
    """
    displaced = max(len(evidence) - MAX_EVIDENCE_CITATIONS, 0)
    return tuple(evidence[displaced:]), elided + displaced


def _installed(record: MemoryRecord) -> MemoryRecord:
    """``record`` with its evidence brought under the bound (ADR-0086 §2).

    Applied at **every install** and at no retirement — ADR-0081 §1's distinction,
    the one :func:`_installed_at` already implements. A ``SUPERSEDE`` whose target
    is a legacy over-bound record retires it through :func:`_close_window` with its
    tuple and its ``evidence_elided`` untouched, because a retirement asserts
    nothing new about the warrant and truncating there would make a stored record
    unreadable on its way off the read path.

    A no-op for anything already under the bound. Where it bites it rebuilds
    :class:`Provenance` through ``model_validate``, so the type's validators run on
    the value that is stored rather than being skipped by ``model_copy(update=...)``
    (ADR-0026 §2).
    """
    provenance = record.provenance
    retained, elided = _bounded_evidence(provenance.evidence, elided=provenance.evidence_elided)
    if elided == provenance.evidence_elided:
        return record
    bounded = Provenance.model_validate(
        provenance.model_dump() | {"evidence": retained, "evidence_elided": elided}
    )
    return record.model_copy(update={"provenance": bounded})


def _corroborates(target: MemoryRecord, incoming: MemoryRecord) -> bool:
    """Does this fold contribute evidence and currency and nothing else?

    **Two pairings, one rule**, exactly as ``MemoryIngestor`` has it. ADR-0103 §6
    rules it for a ``DERIVED`` proposal onto an ``ATTESTED`` target; ADR-0121 §4's
    second clause applies the same rule to a ``USER_ASSERTED`` proposal onto a
    ``USER_ASSERTED`` target, where the same authority is saying the same thing
    again and no warrant arrives that the record did not already have.

    Keyed on both bands and on neither record's confidence for ADR-0103 §6's
    pairing, so the same fold folds the same way at ``0.7`` and at ``1.0``; only the
    ``1.0`` case was #646's crash. ``ATTESTED`` is named on the target side rather
    than the rule being stated as "a ``DERIVED`` proposal onto any target", because
    the only fold that reaches an ``ASSERTED`` target is ADR-0121 §5's, whose
    incoming record is not ``DERIVED`` (:func:`_refuse_unsafe_fold` clause 1).
    ADR-0121's pairing is keyed on the **sources** and not on the ``ASSERTED`` band,
    following that clause's own words rather than enrolling a ``MemorySource`` added
    into the band later.

    **Selected by the pairing, never by re-testing agreement.**
    :func:`_refuse_unsafe_fold` has already refused every ``USER_ASSERTED`` →
    ``USER_ASSERTED`` fold whose records do not agree, so this arm is reachable only
    when they do; and were that refusal ever weakened, selecting on agreement here
    would send the slip to the *ordinary* arm, which would overwrite the user's
    assertion with the incoming content. The safe arm is the one that catches it.

    Duplicated from ``MemoryIngestor`` (golden rule 1), and duplicated *because*
    ADR-0103 §7 declines to promote §6 to the conformance suite: with no shared case
    holding the two copies together, this fake follows the ingestor deliberately
    rather than mechanically. ADR-0121 §4's clause is likewise unpinned by the
    suite, which pins the *refusals* (§5) rather than the fold's composition.

    Args:
        target: The stored record the ruling folds into.
        incoming: The proposed record being folded in.

    Returns:
        Whether the survivor is the target contributed to, rather than the incoming
        record wearing the target's id.
    """
    if (
        target.provenance.source is MemorySource.USER_ASSERTED
        and incoming.provenance.source is MemorySource.USER_ASSERTED
    ):
        return True
    return (
        band_of(target.provenance.source) is BeliefBand.ATTESTED
        and band_of(incoming.provenance.source) is BeliefBand.DERIVED
    )


def _confirming_instant(
    target: Provenance, incoming: Provenance, *, now: datetime
) -> datetime | None:
    """The survivor's ``last_confirmed_at`` — ADR-0103 §6's rule, ADR-0109 §5's shape.

    The later of the two records' **usable** confirming instants; the usable one
    where only one is usable; ``None`` where neither is. Usable means not ``None``
    and not in the writer's future at the moment of the fold, on this fake's own
    injected clock.

    Duplicated from ``MemoryIngestor`` rather than shared, exactly as this module's
    other contract helpers are: ``ai_assistant.testing`` may not import a subsystem
    (golden rule 1). ADR-0109 §9 declines to promote its §5 and §6 to the ``MemoryWriter``
    conformance suite — a writer that composes currency differently conforms, or
    ADR-0028 §8's exclusion is void — while requiring **this** fake to implement
    them identically to the ingestor, so a lane testing against it observes the
    ingestor's behaviour. That is an obligation on the canonical fake, not on every
    implementation of the Protocol, and it is why the clock is here at all: without
    it the fake would take a future-dated ``reported_at`` where the ingestor takes
    the usable January instant, and every fold test written against this double
    would certify a survivor production never writes.

    Args:
        target: The stored record's provenance.
        incoming: The proposed record's provenance.
        now: This writer's clock reading, defining "our future" for this fold.

    Returns:
        The instant the survivor carries, or ``None`` for ADR-0103 §9's unknown.
    """
    usable = [
        instant
        for instant in (target.last_confirmed_at, incoming.last_confirmed_at)
        if instant is not None and instant <= now
    ]
    return max(usable, default=None)


def _merge(target: MemoryRecord, incoming: MemoryRecord, *, now: datetime) -> MemoryRecord:
    """Fold ``incoming`` into ``target``, keeping the target's id.

    A minimal fold — newer content wins, confidence taken as the maximum. Only
    the evidence half is contract (ADR-0040 §5a): a ``REINFORCE`` retains
    **both** records' ``evidence``, **up to** :data:`MAX_EVIDENCE_CITATIONS`,
    beyond which the oldest are displaced and counted (ADR-0086 §3, partially
    superseding §5a). How content and confidence combine is `memory`'s own rule,
    which the conformance suite deliberately does not pin.

    The union is bounded before the ``Provenance`` is constructed, so its
    validators run on the value stored. The fold is the one install drawing from
    **two** sources, so both records' ``evidence_elided`` are summed — even when
    the union fits and nothing is displaced (ADR-0086 §4).

    **A ``DERIVED`` record folded onto an ``ATTESTED`` one corroborates rather than
    accumulates** (ADR-0103 §6): the whole target record survives — content,
    ``source``, ``attestation``, confidence, window and expiry — and the incoming
    record contributes its evidence and nothing else. Not contract either, and
    mirrored here for the reason every other unpinned rule is: a fake that folded
    differently would let an `orchestration` test see a survivor production never
    writes, and in this pairing production used to raise a ``ValidationError`` out
    of ``core`` and write nothing at all (#646).

    **An agreeing restatement of the user's own assertion folds the same way**
    (ADR-0121 §4's second clause, :func:`_corroborates`' second pairing), and here
    the mirroring is load-bearing rather than merely faithful: ADR-0121 §5's
    exception to the clause-1 fold refusal rests on the fold writing the target's
    own bytes back at the target's own id. A fake that took the ordinary arm would
    permit the fold while performing the write the exception's whole argument says
    it does not perform, certifying a consumer against a survivor that overwrites
    what the user told us.

    The ``attestation`` is the **incoming** one on the ordinary arm (ADR-0092 §6),
    which is required rather than a choice: this ``Provenance`` is built field by
    field, so its iff validator would raise on an attested fold carrying none. It
    follows the rule ``source`` and ``last_updated`` already follow — newer content
    wins, and the attestation describes the content that survived. The
    corroboration arm keeps that same property by keeping the *target's*
    attestation, beside the target's ``source`` and the target's text.
    ``last_updated`` comes from the incoming record on both arms: it is transaction
    time (ADR-0045 §3), not one of the belief properties ADR-0103 §6 withholds.

    ``derived_from_external`` is the **disjunction** of both sides on both arms
    (ADR-0106 §4), and this one is mirrored because the alternative is a fake that
    *launders*: this ``Provenance`` is built field by field, so omitting the field
    would default it to ``False`` and clear a tainted target on the first clean
    reinforcement — the exact laundering ADR-0106 §4 exists to stop, performed by
    the double a subsystem reaches for when it does not want `memory`'s internals.
    Not promoted to the ``MemoryWriter`` conformance suite: ADR-0106 §10 assigns
    the test to the lane changing `memory`'s fold, and ADR-0028 §8 and ADR-0040
    §5a keep the fold's own composition rules off that contract. It is pinned
    against both writers directly instead.

    ``last_confirmed_at`` is **composed** on both arms rather than inherited from
    either side (:func:`_confirming_instant`, ADR-0109 §5, §6): the later of the two
    records' usable instants, the usable one where only one is, and ``None`` where
    neither is. Not contract — ADR-0109 §9 leaves a writer free to compose currency
    differently — and mirrored here because a fake that diverged would make every
    fold test written against it a test of nothing. Nothing needs the cited episodes
    to compute it: the producers captured their instants before ADR-0086 §3's bound
    could displace anything, so the bound displaces citations and nothing else.

    Args:
        target: The stored record the ruling folds into.
        incoming: The proposed record being folded in.
        now: This writer's clock reading, which defines "our future" for
            :func:`_confirming_instant` and for nothing else. Passed in rather
            than read here, so the caller keeps the guard that turns a bad
            reading into a ``MemoryStoreError``.

    Returns:
        The survivor: the target's record on the corroboration arm, the incoming
        record wearing the target's id on the ordinary one.
    """
    union = tuple(dict.fromkeys([*target.provenance.evidence, *incoming.provenance.evidence]))
    evidence, elided = _bounded_evidence(
        union,
        elided=target.provenance.evidence_elided + incoming.provenance.evidence_elided,
    )
    # Selected once, before the arms: ADR-0109 §6 makes the rule identical on both.
    confirmed_at = _confirming_instant(target.provenance, incoming.provenance, now=now)
    # Likewise selected once, before the arms (ADR-0106 §4): the clause is stated
    # over the fold as a disjunction, so neither arm may read one side alone.
    tainted = target.provenance.derived_from_external or incoming.provenance.derived_from_external
    if _corroborates(target, incoming):
        corroborated = Provenance(
            source=target.provenance.source,
            confidence=target.provenance.confidence,
            evidence=evidence,
            evidence_elided=elided,
            last_updated=incoming.provenance.last_updated,
            attestation=target.provenance.attestation,
            derived_from_external=tainted,
            last_confirmed_at=confirmed_at,
        )
        return target.model_copy(update={"provenance": corroborated})
    provenance = Provenance(
        source=incoming.provenance.source,
        confidence=max(target.provenance.confidence, incoming.provenance.confidence),
        evidence=evidence,
        evidence_elided=elided,
        last_updated=incoming.provenance.last_updated,
        attestation=incoming.provenance.attestation,
        derived_from_external=tainted,
        last_confirmed_at=confirmed_at,
    )
    return incoming.model_copy(update={"id": target.id, "provenance": provenance})
