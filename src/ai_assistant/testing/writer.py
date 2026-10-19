"""A canonical :class:`~ai_assistant.core.protocols.MemoryWriter` fake.

The shared test double for the ``MemoryWriter`` contract (ADR-0028, ADR-0328 §11), so
a subsystem that commits memory through the write path — `orchestration`, above all —
can exercise it *without importing the memory subsystem's internals* (CLAUDE.md golden
rule 1).

It is a minimal, contract-correct writer over an injected store and policy: it refuses
a proposal whose supports point at an episode the store does not hold, resolves
conflicts, asks the policy to rule, and applies the ruling as ADR-0328 §11 says — an
``ACCEPT`` installs the memory, a ``REINFORCE`` adds its supports to the target, a
``SUPERSEDE`` installs it at a fresh id and ends what it retires. It applies one
operation to one stored memory through its own transition
(:func:`~ai_assistant.testing._operations.applied_operation`), since no testing module
imports ``memory``; the shared conformance suite holds it and ``MemoryIngestor``'s to
the same record and the same refusals. Only
the behaviour pinned by the shared conformance suite is contract; its conflict
heuristic, the *value* of its ceiling and its clock are deliberately not.

Beyond the contract it records every proposal it was handed on :attr:`calls`, so a test
can assert what its subject actually delegated.
"""

from __future__ import annotations

import asyncio
import unicodedata
import uuid
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, assert_never

from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    FoldOntoCitedRecordError,
    MemoryStoreConflictError,
    MemoryStoreError,
    MemoryStoreStaleError,
    SelfConsumingWriteError,
    UnresolvedEvidenceError,
)
from ai_assistant.core.types import (
    MAX_TOPICS_PER_RECORD,
    BeliefBand,
    ConflictRelation,
    DataTier,
    Memory,
    MemoryDecisionKind,
    MemoryIngestResult,
    MemoryKind,
    MemoryOperation,
    MemoryOperationKind,
    MemorySupport,
    MemoryWrite,
    MemoryWriteMode,
    SupportDirection,
    SupportOrigin,
    Validity,
    part_episode,
    record_band,
)
from ai_assistant.testing._operations import applied_operation

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore
    from ai_assistant.core.types import (
        MemoryChange,
        MemoryDecision,
        MemoryRecord,
        MemoryUpdateProposal,
    )

_DEFAULT_CONFLICT_THRESHOLD = 0.75

#: The ceiling on the conflicts one ingest resolves (ADR-0079 §1), matching
#: ``MemoryIngestor``'s default. Duplicated rather than imported: the two writers must
#: agree about whether a write is *possible*.
_DEFAULT_CONFLICT_LIMIT = 100

#: Bound on the supersession re-mint loop, matching ``MemoryIngestor`` (ADR-0045 §4).
_MAX_SUPERSEDE_ATTEMPTS = 5


def _uuid() -> str:
    return str(uuid.uuid4())


# The three band classes ``MemoryIngestor`` holds, duplicated rather than imported
# (golden rule 1) and for its reasons (ADR-0092 §5): each answers its own question,
# read through ADR-0328 §12.

#: The **retirement class** (ADR-0050 §1, ADR-0079 §3, ADR-0092 §4).
_RETIREMENT_CLASS = frozenset({BeliefBand.DERIVED, BeliefBand.ATTESTED})

#: The **reinforce-safe class** (ADR-0038 §2a, ADR-0045 §5b, ADR-0121 §5).
_REINFORCE_SAFE = frozenset({BeliefBand.DERIVED, BeliefBand.ASSERTED})

#: The **incoming** bands clause 1's agreeing-fold exception admits (ADR-0214 §3).
_AGREEING_FOLD_INCOMING = frozenset({BeliefBand.ASSERTED, BeliefBand.DERIVED})

#: The rulings that dispatch a write, gated by check 0 (ADR-0078 §5b).
_WRITE_PRODUCING_KINDS = frozenset(MemoryDecisionKind) - {
    MemoryDecisionKind.ASK_USER,
    MemoryDecisionKind.REJECT,
}

#: The relations that put a conflict beyond retirement (ADR-0159 §5).
_UNRETIRABLE_RELATIONS = frozenset({ConflictRelation.RESTATES, ConflictRelation.ADDS})


def _utcnow() -> datetime:
    return datetime.now(UTC)


class StubConflictReconciler(Protocol):
    """The reconciler seam :class:`FakeMemoryWriter` accepts (ADR-0159 §2, §10).

    Duplicated from ``memory`` rather than imported (golden rule 1). This fake ships no
    implementation of it: what a canonical fake owes is the *seam*, so a consumer's
    test can inject a stub and see the writer honour ADR-0159 §5's exclusion. An
    implementation owes ADR-0159 §3's never-raises contract; this fake guards against
    one that does not, as ``MemoryIngestor`` does.
    """

    async def reconcile(
        self,
        proposal: MemoryUpdateProposal,
        conflicts: Sequence[MemoryRecord],
    ) -> Mapping[str, ConflictRelation]:
        """Label what can be labelled, keyed by record id.

        Args:
            proposal: The proposal being ingested.
            conflicts: The resolved conflict set, best-ranked first.

        Returns:
            A relation for each member a determination was made about.
        """
        ...


def _asserted(record: MemoryRecord) -> bool:
    return record_band(record) is BeliefBand.ASSERTED


def _cited_ids(memory: Memory) -> frozenset[str]:
    """The episodes ``memory``'s supports point at: what it cites (ADR-0328 §12).

    A legacy support carries its record whole (§16:4), so installing at that record's
    id consumes no warrant, and it is no citation here.
    """
    return frozenset(
        episode
        for support in memory.supports
        if (episode := part_episode(support.points_at)) is not None
    )


def _may_reconcile(proposal: MemoryUpdateProposal, conflicts: Sequence[MemoryRecord]) -> bool:
    """ADR-0159 §2's invocation condition, mirroring ``MemoryIngestor``'s.

    The floor is restated here rather than shared, since the predicate production
    shares lives in ``ai_assistant.memory.policy``, out of reach (golden rule 1).
    """
    memory = proposal.proposed
    if memory.band is BeliefBand.ASSERTED or any(_asserted(c) for c in conflicts):
        return False
    if proposal.sensitivity is DataTier.SECRET:
        return False
    if memory.band is BeliefBand.DERIVED and all(
        part_episode(support.points_at) is None for support in memory.supports
    ):
        return False
    return not (
        memory.band is BeliefBand.DERIVED
        and memory.rests_on_outside_content
        and proposal.confirmation is None
    )


def _agreement_form(content: str) -> str:
    """ADR-0121 §1's four transformations, in order, duplicated from ``memory``."""
    return " ".join(unicodedata.normalize("NFC", content).casefold().split())


def _agrees(left: MemoryRecord, right: MemoryRecord) -> bool:
    """Whether two records agree under ADR-0121 §1 — ``kind`` and ``content``, nothing else."""
    return left.kind == right.kind and _agreement_form(left.content) == _agreement_form(
        right.content
    )


def _confirmation_covers(
    target: MemoryRecord,
    proposal: MemoryUpdateProposal,
    kind: MemoryDecisionKind,
    *,
    resolved: tuple[str, ...],
) -> bool:
    """Whether a confirmation authorises retiring ``target`` (ADR-0078 §5b's five checks)."""
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


def _refuse_unsafe_fold(
    target: MemoryRecord,
    proposal: MemoryUpdateProposal,
    kind: MemoryDecisionKind,
    *,
    resolved: tuple[str, ...],
) -> None:
    """The two fold refusals ``MemoryIngestor`` carries, read through ADR-0328 §12.

    Raises:
        MemoryStoreError: If the fold lands on an ``ASSERTED`` target no exception
            admits, or reinforces an asserted proposal onto a target outside the
            reinforce-safe class.
    """
    incoming = proposal.proposed
    agreeing = (
        kind is MemoryDecisionKind.REINFORCE
        and incoming.band in _AGREEING_FOLD_INCOMING
        and _agrees(target, incoming)
    )
    if (
        _asserted(target)
        and not _confirmation_covers(target, proposal, kind, resolved=resolved)
        and not agreeing
    ):
        msg = f"refusing to fold onto {target.id!r}: a user-asserted memory (ADR-0045 §5)"
        raise MemoryStoreError(msg)
    if (
        kind is MemoryDecisionKind.REINFORCE
        and incoming.band is BeliefBand.ASSERTED
        and record_band(target) not in _REINFORCE_SAFE
    ):
        msg = f"refusing to reinforce {target.id!r} with a user assertion (ADR-0038 §2a)"
        raise MemoryStoreError(msg)


def _refuse_retiring_a_related_conflict(
    target: MemoryRecord, kind: MemoryDecisionKind, relations: Mapping[str, ConflictRelation]
) -> None:
    """Refuse a ``SUPERSEDE`` naming a ``RESTATES`` or ``ADDS`` conflict (ADR-0159 §5).

    Raises:
        MemoryStoreError: If it does.
    """
    if kind is MemoryDecisionKind.SUPERSEDE and relations.get(target.id) in _UNRETIRABLE_RELATIONS:
        msg = f"refusing to supersede {target.id!r}: a related conflict is never retired"
        raise MemoryStoreError(msg)


def _refuse_before_write(
    decision: MemoryDecision, proposal: MemoryUpdateProposal, *, resolved: tuple[str, ...]
) -> None:
    """The refusals between the ruling and the write dispatch, in ``MemoryIngestor``'s order.

    Check 0 on secret-tier data (ADR-0078 §5b), a ``STORE_TEMPORARY`` ruling (ADR-0328
    §10:3), and a write at an id the proposal's supports point at (ADR-0081 §1).

    Raises:
        MemoryStoreError: On the first two.
        FoldOntoCitedRecordError: On a ``REINFORCE`` onto a cited record.
        SelfConsumingWriteError: On an ``ACCEPT`` at a cited id.
    """
    proposed = proposal.proposed
    if decision.kind in _WRITE_PRODUCING_KINDS and proposal.sensitivity is DataTier.SECRET:
        msg = f"refusing to write {proposed.id!r}: secret-tier data (ADR-0004 §3, ADR-0078 §5b)"
        raise MemoryStoreError(msg)
    if decision.kind is MemoryDecisionKind.STORE_TEMPORARY:
        msg = "refusing a STORE_TEMPORARY ruling: nothing is stored tentatively (ADR-0328 §10:3)"
        raise MemoryStoreError(msg)
    destination = _installed_at(decision, proposed, resolved=resolved)
    if destination is not None and destination in _cited_ids(proposed):
        refusal = (
            FoldOntoCitedRecordError
            if decision.kind is MemoryDecisionKind.REINFORCE
            else SelfConsumingWriteError
        )
        msg = f"refusing to write {proposed.id!r} at {destination!r}, an id it cites (ADR-0081 §1)"
        raise refusal(msg)


def _installed_at(
    decision: MemoryDecision, proposed: Memory, *, resolved: tuple[str, ...]
) -> str | None:
    """The id this ruling would install the proposal at, if any (ADR-0081 §1)."""
    match decision.kind:
        case MemoryDecisionKind.ACCEPT:
            return proposed.id
        case MemoryDecisionKind.REINFORCE:
            return decision.target_id if decision.target_id in resolved else None
        case (
            MemoryDecisionKind.SUPERSEDE
            | MemoryDecisionKind.REJECT
            | MemoryDecisionKind.ASK_USER
            | MemoryDecisionKind.STORE_TEMPORARY
        ):
            return None
    assert_never(decision.kind)


def _checked_id(id_factory: Callable[[], str], *, owner: str) -> str:
    """Read the injected id factory, guarding its output as ``MemoryIngestor`` does.

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
        msg = f"the id factory injected into {owner} did not return a non-empty built-in str"
        raise MemoryStoreError(msg)
    return minted


def _retirement_set(
    target: MemoryRecord,
    conflicts: list[MemoryRecord],
    *,
    proposal: MemoryUpdateProposal,
    resolved: tuple[str, ...],
    relations: Mapping[str, ConflictRelation],
) -> list[MemoryRecord]:
    """The whole set a ``SUPERSEDE`` retires, as ``MemoryIngestor`` computes it."""
    labelled = any(relations.get(c.id) is ConflictRelation.CONTRADICTS for c in conflicts)
    others = [
        conflict
        for conflict in conflicts
        if conflict.id != target.id
        and relations.get(conflict.id) not in _UNRETIRABLE_RELATIONS
        and (
            (
                record_band(conflict) in _RETIREMENT_CLASS
                and (not labelled or relations.get(conflict.id) is ConflictRelation.CONTRADICTS)
            )
            or (
                _asserted(conflict)
                and _confirmation_covers(
                    conflict, proposal, MemoryDecisionKind.SUPERSEDE, resolved=resolved
                )
            )
        )
    ]
    return [target, *others]


def _bounded_topics(admitted: Sequence[str]) -> tuple[str, ...]:
    """ADR-0213 §8's retained subset, stored in §1's canonical order."""
    admitted_once = tuple(dict.fromkeys(admitted))
    return tuple(sorted(admitted_once[:MAX_TOPICS_PER_RECORD]))


def _installed(memory: Memory) -> Memory:
    """``memory`` with its topics under :data:`MAX_TOPICS_PER_RECORD` (ADR-0213 §1)."""
    topics = _bounded_topics(sorted(memory.topics))
    return memory if topics == memory.topics else memory.model_copy(update={"topics": topics})


def _supersede(incoming: Memory, new_id: str, retired: Sequence[str]) -> Memory:
    """``incoming`` at a fresh id with an open window, naming what it replaces (§11:7)."""
    first, *rest = incoming.operations
    create = first.model_copy(
        update={"replaces": tuple(dict.fromkeys([*first.replaces, *retired]))}
    )
    try:
        return Memory.model_validate(
            incoming.model_dump()
            | {"id": new_id, "validity": Validity(), "operations": (create, *rest)}
        )
    except ValidationError as exc:
        # A proposal that cannot stand live — one already ended or marked wrong keeps
        # its status, which an open window contradicts (ADR-0328 §3:4) — is refused as
        # this writer's error, never as a raw validation failure.
        msg = f"cannot supersede with {incoming.id!r}: it cannot stand live"
        raise MemoryStoreError(msg) from exc


def _ended(target: MemoryRecord, successor: Memory, now: datetime) -> Memory:
    """``target`` ended by a supersession, as ``MemoryIngestor`` ends it (ADR-0328 §11:7).

    Raises:
        MemoryStoreError: If the end is refused, or the target already carries the part.
    """
    first = successor.supports[0]
    if not isinstance(target, Memory) or target.support_at(first.points_at) is not None:
        msg = f"cannot retire {target.id!r} (ADR-0328 §11:7)"
        raise MemoryStoreError(msg)
    against = MemorySupport.model_validate(
        first.model_dump()
        | {"direction": SupportDirection.AGAINST, "backs_as_worded": False, "added_at": now}
    )
    end = MemoryOperation(
        kind=MemoryOperationKind.END,
        cites=first.points_at,
        note="superseded by a memory that overturns it",
        at=now,
        by=successor.operations[0].by,
        successor=successor.id,
    )
    try:
        return applied_operation(target, end, support=against)
    except ValueError as exc:
        msg = f"cannot retire {target.id!r}: {exc}"
        raise MemoryStoreError(msg) from exc


def _reinforced(target: MemoryRecord, incoming: Memory, *, now: datetime) -> Memory:
    """``target`` with ``incoming``'s supports added, one add support each (§11:6).

    Raises:
        MemoryStoreError: If ``target`` is not a memory, or an add support is refused.
    """
    if not isinstance(target, Memory):
        msg = f"cannot reinforce {target.id!r}: not a memory"
        raise MemoryStoreError(msg)
    folded = target
    for support in incoming.supports:
        if folded.support_at(support.points_at) is not None:
            continue
        if support.origin is SupportOrigin.CONFIRMATION and not _agrees(target, incoming):
            msg = (
                f"cannot reinforce {target.id!r}: a confirmation backs only a wording that "
                f"agrees with the statement the user approved (ADR-0328 §4:6)"
            )
            raise MemoryStoreError(msg)
        operation = MemoryOperation(
            kind=MemoryOperationKind.ADD_SUPPORT,
            cites=support.points_at,
            note="added by a proposal that agrees with this memory",
            at=now,
            by=incoming.operations[0].by,
        )
        try:
            folded = applied_operation(
                folded, operation, support=support.model_copy(update={"added_at": now})
            )
        except ValueError as exc:
            msg = f"cannot reinforce {target.id!r}: {exc}"
            raise MemoryStoreError(msg) from exc
    carried = set(target.topics)
    topics = _bounded_topics(
        [*sorted(target.topics), *sorted(t for t in incoming.topics if t not in carried)]
    )
    return folded.model_copy(
        update={"placement": target.placement.folded_with(incoming.placement), "topics": topics}
    )


class FakeMemoryWriter:
    """A ``MemoryWriter`` test double that really writes to an injected store.

    Structurally implements :class:`~ai_assistant.core.protocols.MemoryWriter`. Real
    rather than inert on purpose: a writer that recorded proposals and stored nothing
    would let a consumer's test pass while its closed loop stayed open (ADR-0028).
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
        reconciler: StubConflictReconciler | None = None,
    ) -> None:
        """Create the fake writer.

        Args:
            store: Where memories are persisted and conflicts sought. A consumer's test
                must pass the *same* store its subject retrieves from (ADR-0028 §4).
            policy: The policy that rules on each proposal.
            conflict_threshold: Minimum retrieval score for a conflict.
            conflict_limit: The **ceiling** on the conflicts one ingest resolves
                (ADR-0079 §1).
            now: Clock an operation's instant is read from; guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, as ``MemoryIngestor``'s.
            id_factory: Mints the fresh id a ``SUPERSEDE`` writes its memory at,
                guarded at its output by :func:`_checked_id`.
            reconciler: A stub determining ADR-0159 §1 relations, with the same ruled,
                safe absence the production writer has (ADR-0159 §6).
        """
        self._store = store
        self._policy = policy
        self._conflict_threshold = conflict_threshold
        self._conflict_limit = conflict_limit
        self._clock = checked_clock(now, owner="FakeMemoryWriter")
        self._id_factory = id_factory
        self._reconciler = reconciler
        self._lock = asyncio.Lock()
        self.calls: list[MemoryUpdateProposal] = []

    async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        """Record the proposal, then resolve, rule and apply (ADR-0328 §11:4).

        Observes the caller's proposal once, on the coroutine's first executed line
        (ADR-0065), and carries ``MemoryIngestor``'s refusals in its order.

        Raises:
            UnresolvedEvidenceError: If a support points at an episode the store does
                not hold; nothing is written and the policy is not asked.
            MemoryStoreError: On every other refusal ``MemoryIngestor`` makes.
        """
        observed = proposal.model_copy(deep=True)
        # One public call is one entry, however many attempts the stale retry makes.
        self.calls.append(observed.model_copy(deep=True))
        async with self._lock:
            try:
                return await self._ingest(observed)
            except MemoryStoreStaleError:
                return await self._ingest(observed)

    async def apply(self, change: MemoryChange) -> None:
        """Apply one operation to one stored memory, as ``MemoryIngestor`` does (§11:3).

        Raises:
            UnresolvedEvidenceError: If the support it adds, or the successor's, points
                at an episode the store does not hold.
            MemoryStoreStaleError: If the stored memory is not the one read.
            MemoryStoreConflictError: If the successor's id names a stored record.
            MemoryStoreError: If §4, §5 or §6:5 refuses the operation.
        """
        observed = change.model_copy(deep=True)
        async with self._lock:
            memory = observed.memory
            # §4:7 binds a support actually added: one the memory already carries
            # changes nothing and is no error (§4:8), its episode gone or not.
            carried = observed.support is not None and memory.support_at(observed.support.points_at)
            added = () if observed.support is None or carried else (observed.support,)
            successor = () if observed.successor is None else observed.successor.supports
            await self._require_held_episodes(memory.id, (*added, *successor))
            try:
                after = applied_operation(
                    memory, observed.operation, support=observed.support, question=observed.question
                )
            except ValueError as exc:
                msg = f"refusing to apply a {observed.operation.kind} to {memory.id!r}: {exc}"
                raise MemoryStoreError(msg) from exc
            if after is memory:
                return
            batch = [
                MemoryWrite(
                    record=after,
                    mode=MemoryWriteMode.IF_UNCHANGED,
                    expected_revision=memory.revision,
                )
            ]
            if observed.successor is not None:
                batch.append(
                    MemoryWrite(
                        record=_installed(observed.successor),
                        mode=MemoryWriteMode.INSERT_IF_ABSENT,
                    )
                )
            await self._store.write_atomic(batch)

    async def _ingest(self, observed: MemoryUpdateProposal) -> MemoryIngestResult:
        await self._require_held_episodes(observed.proposed.id, observed.proposed.supports)
        conflicts = await self._conflicts_for(observed.proposed)
        resolved = tuple(record.id for record in conflicts)
        ruled = observed.model_copy(update={"conflicts": resolved})
        relations = await self._relations_for(ruled, conflicts)
        decision = await self._policy.decide(
            ruled,
            conflicts=conflicts,
            relations=None
            if relations is None or self._reconciler is None
            else MappingProxyType(dict(relations)),
        )
        _refuse_before_write(decision, observed, resolved=resolved)
        record_id = await self._apply(
            decision, observed, conflicts, resolved=resolved, relations=relations or {}
        )
        return MemoryIngestResult(decision=decision, record_id=record_id, conflicts=resolved)

    async def _relations_for(
        self, proposal: MemoryUpdateProposal, conflicts: Sequence[MemoryRecord]
    ) -> dict[str, ConflictRelation] | None:
        """The relations this writer holds for one ingest, or ``None`` (ADR-0159 §2, §3, §6)."""
        if not _may_reconcile(proposal, conflicts):
            return None
        memory = proposal.proposed
        own = {c.id: ConflictRelation.RESTATES for c in conflicts if _agrees(c, memory)}
        if self._reconciler is None:
            return own
        try:
            determined = await self._reconciler.reconcile(proposal, conflicts)
            labelled = {
                c.id: determined[c.id] for c in conflicts if c.id not in own and c.id in determined
            }
        except Exception:
            return own
        return labelled | own

    async def _require_held_episodes(
        self, memory_id: str, supports: Sequence[MemorySupport]
    ) -> None:
        """Refuse supports pointing at an episode the store does not hold (ADR-0328 §4:7).

        Raises:
            UnresolvedEvidenceError: If any support's episode does not resolve.
        """
        episodes = list(
            dict.fromkeys(
                episode
                for episode in (part_episode(support.points_at) for support in supports)
                if episode is not None
            )
        )
        if not episodes:
            return
        held = await self._store.get_many(episodes)
        unresolved = [
            episode
            for episode in episodes
            if (found := held.get(episode)) is None or found.kind != MemoryKind.EPISODIC.value
        ]
        if unresolved:
            msg = (
                f"refusing to write {memory_id!r}: its supports point at an episode this "
                f"store does not hold — {', '.join(repr(one) for one in unresolved)} "
                f"(ADR-0328 §4:7)"
            )
            raise UnresolvedEvidenceError(msg, unresolved)

    async def _conflicts_for(self, memory: Memory) -> list[MemoryRecord]:
        """Every conflict retrieval surfaced, or a refusal above the ceiling (ADR-0079 §1).

        Raises:
            MemoryStoreError: If retrieval surfaced more conflicts than this writer
                resolves in one ingest.
        """
        found = await self._store.search(
            memory.content, limit=self._conflict_limit + 2, kinds=[MemoryKind.MEMORY]
        )
        conflicts = [
            match
            for match in found.records
            if match.id != memory.id and (match.score or 0.0) >= self._conflict_threshold
        ]
        if len(conflicts) > self._conflict_limit:
            msg = (
                f"refusing to ingest {memory.id!r}: conflict resolution surfaced more than "
                f"{self._conflict_limit} conflicting records (ADR-0079 §1)"
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
        relations: Mapping[str, ConflictRelation],
    ) -> str | None:
        proposed = proposal.proposed
        match decision.kind:
            case MemoryDecisionKind.ACCEPT:
                written = await self._store.write_atomic(
                    [
                        MemoryWrite(
                            record=_installed(proposed), mode=MemoryWriteMode.INSERT_IF_ABSENT
                        )
                    ]
                )
                return written[0]
            case MemoryDecisionKind.REINFORCE | MemoryDecisionKind.SUPERSEDE:
                target = next((c for c in conflicts if c.id == decision.target_id), None)
                if target is None:
                    msg = f"fold target {decision.target_id!r} is not among the conflicts"
                    raise MemoryStoreError(msg)
                _refuse_unsafe_fold(target, proposal, decision.kind, resolved=resolved)
                _refuse_retiring_a_related_conflict(target, decision.kind, relations)
                if decision.kind is MemoryDecisionKind.SUPERSEDE:
                    retiring = _retirement_set(
                        target,
                        conflicts,
                        proposal=proposal,
                        resolved=resolved,
                        relations=relations,
                    )
                    return await self._apply_supersede(retiring, proposed)
                folded = _installed(_reinforced(target, proposed, now=self._now_utc()))
                written = await self._store.write_atomic(
                    [
                        MemoryWrite(
                            record=folded,
                            mode=MemoryWriteMode.IF_UNCHANGED,
                            expected_revision=target.revision,
                        )
                    ]
                )
                return written[0]
            case _:  # REJECT, ASK_USER — nothing is written.
                return None

    async def _apply_supersede(self, targets: list[MemoryRecord], proposed: Memory) -> str:
        """End every target and install the proposal at a fresh id, atomically (§11:7).

        Raises:
            MemoryStoreError: If an end is refused, or the bounded re-mint finds no free
                id; every target left live and unchanged.
        """
        now = self._now_utc()
        retired_ids = [target.id for target in targets]
        cited = _cited_ids(proposed)
        last_conflict: MemoryStoreConflictError | None = None
        for _ in range(_MAX_SUPERSEDE_ATTEMPTS):
            new_id = _checked_id(self._id_factory, owner="FakeMemoryWriter")
            if new_id in cited or new_id in retired_ids:
                last_conflict = MemoryStoreConflictError(f"minted id {new_id!r}; re-minting")
                continue
            successor = _installed(_supersede(proposed, new_id, retired_ids))
            batch = [
                MemoryWrite(
                    record=_ended(target, successor, now),
                    mode=MemoryWriteMode.IF_UNCHANGED,
                    expected_revision=target.revision,
                )
                for target in targets
            ]
            batch.append(MemoryWrite(record=successor, mode=MemoryWriteMode.INSERT_IF_ABSENT))
            try:
                await self._store.write_atomic(batch)
            except MemoryStoreConflictError as exc:
                last_conflict = exc
                continue
            return new_id
        msg = (
            f"supersession could not mint a free id after {_MAX_SUPERSEDE_ATTEMPTS} attempts; "
            f"the targets are left live and unchanged"
        )
        raise MemoryStoreError(msg) from last_conflict

    def _now_utc(self) -> datetime:
        """The guarded clock's reading, as `memory`'s own error (ADR-0026 §4).

        Raises:
            MemoryStoreError: If the injected clock's reading is not conforming.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise MemoryStoreError(str(exc)) from exc
