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
the same record and the same refusals. It records a track-record entry, and carries
the observer's admission rules — an observer's inference and a proposal's one retiring
operation (ADR-0329 §9:7, §12:4) — through its own copy of them
(:mod:`ai_assistant.testing._observer_writes`). Only
the behaviour pinned by the shared conformance suite is contract; its conflict
heuristic, the *value* of its ceiling and its clock are deliberately not.

Beyond the contract it records every proposal it was handed on :attr:`calls`, so a test
can assert what its subject actually delegated.
"""

from __future__ import annotations

import asyncio
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from math import sqrt
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
    BeliefBand,
    ConflictRelation,
    DataTier,
    EpisodicMemory,
    Memory,
    MemoryDecisionKind,
    MemoryIngestResult,
    MemoryKind,
    MemoryLabelResult,
    MemoryOperation,
    MemoryOperationKind,
    MemoryRetirement,
    MemorySupport,
    MemoryWrite,
    MemoryWriteMode,
    MemoryWriterName,
    SituationLabel,
    SupportDirection,
    SupportOrigin,
    Validity,
    names_not_given,
    part_episode,
    record_band,
    stamped_support,
)
from ai_assistant.testing._observer_writes import (
    added_inference_fault,
    inference_fault,
    inference_when_fault,
    replaces_with,
    retired_memory,
    retirement_fault,
)
from ai_assistant.testing._operations import applied_operation
from ai_assistant.testing._placed import (
    added_backing_fault,
    created_fault,
    ordered_episodes,
    placed_fault,
    placed_write,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence, Set

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import Embedder, MemoryPolicy, MemoryStore
    from ai_assistant.core.types import (
        ChannelIdentity,
        Embedding,
        LabelBounds,
        MemoryChange,
        MemoryDecision,
        MemoryLabelChange,
        MemoryRecord,
        MemoryUpdateProposal,
        TrackRecordEntry,
    )

_DEFAULT_CONFLICT_THRESHOLD = 0.75

#: The ceiling on the conflicts one ingest resolves (ADR-0079 §1), matching
#: ``MemoryIngestor``'s default. Duplicated rather than imported: the two writers must
#: agree about whether a write is *possible*.
_DEFAULT_CONFLICT_LIMIT = 100

#: Bound on the supersession re-mint loop, matching ``MemoryIngestor`` (ADR-0045 §4).
_MAX_SUPERSEDE_ATTEMPTS = 5

#: How many of a channel's episode numbers one read takes, matching ``MemoryIngestor``.
_NUMBER_PAGE = 1000


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


def _may_reconcile(proposal: MemoryUpdateProposal) -> bool:
    """ADR-0336 §2's invocation condition, mirroring ``MemoryIngestor``'s.

    The admissibility floor, and no confirmation; no band enters it. The floor is
    restated here rather than shared, since the predicate production shares lives in
    ``ai_assistant.memory.policy``, out of reach (golden rule 1).
    """
    memory = proposal.proposed
    if proposal.confirmation is not None or proposal.sensitivity is DataTier.SECRET:
        return False
    if memory.band is BeliefBand.DERIVED and all(
        part_episode(support.points_at) is None for support in memory.supports
    ):
        return False
    return not (memory.band is BeliefBand.DERIVED and memory.rests_on_outside_content)


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
    """The whole set a ``SUPERSEDE`` retires, as ``MemoryIngestor`` computes it (ADR-0336 §5).

    The target, and beyond it only the retirement-class members this writer holds a
    ``CONTRADICTS`` relation for, plus an assertion a confirmation covers. Duplicated
    rather than imported (§5:4).
    """
    others = [
        conflict
        for conflict in conflicts
        if conflict.id != target.id
        and (
            (
                record_band(conflict) in _RETIREMENT_CLASS
                and relations.get(conflict.id) is ConflictRelation.CONTRADICTS
            )
            or (
                _asserted(conflict)
                and relations.get(conflict.id) not in _UNRETIRABLE_RELATIONS
                and _confirmation_covers(
                    conflict, proposal, MemoryDecisionKind.SUPERSEDE, resolved=resolved
                )
            )
        )
    ]
    return [target, *others]


def _contradicted(
    decision: MemoryDecision,
    conflicts: Sequence[MemoryRecord],
    relations: Mapping[str, ConflictRelation],
) -> tuple[str, ...]:
    """ADR-0336 §7's field: on an ``ASK_USER``, the assertions held as contradicted."""
    if decision.kind is not MemoryDecisionKind.ASK_USER:
        return ()
    return tuple(
        c.id
        for c in conflicts
        if _asserted(c) and relations.get(c.id) is ConflictRelation.CONTRADICTS
    )


async def _episode_numbers(
    store: MemoryStore, episodes: Set[str], held: Mapping[str, MemoryRecord]
) -> dict[str, int]:
    """The number the store gave each of ``episodes``, read through its channel.

    As ``MemoryIngestor`` reads them (ADR-0348 §3:2, ADR-0283 §1): an episode on no
    channel has no number this reads, and is ordered against no other.
    """
    by_channel: dict[ChannelIdentity, set[str]] = {}
    for episode in episodes:
        found = held.get(episode)
        record = found.processing_record if isinstance(found, EpisodicMemory) else None
        if record is not None and record.trigger.channel is not None:
            by_channel.setdefault(record.trigger.channel, set()).add(episode)
    numbers: dict[str, int] = {}
    for channel, wanted in by_channel.items():
        after: int | None = None
        while wanted:
            page = await store.channel_episode_ids(channel, after=after, limit=_NUMBER_PAGE)
            for one in page:
                if one.episode_id in wanted:
                    numbers[one.episode_id] = one.number
                    wanted.discard(one.episode_id)
            if len(page) < _NUMBER_PAGE:
                break
            after = page[-1].number
    return numbers


def _episode_of(support: MemorySupport, held: Mapping[str, MemoryRecord]) -> EpisodicMemory | None:
    """The episode ``support``'s part points into, as the store holds it, or ``None``."""
    address = part_episode(support.points_at)
    found = None if address is None else held.get(address)
    return found if isinstance(found, EpisodicMemory) else None


def _stamped(memory: Memory, held: Mapping[str, MemoryRecord]) -> Memory:
    """``memory`` with every support carrying its holder, as ``MemoryIngestor``'s (§2:2).

    Raises:
        MemoryStoreError: If a support carries a holder its part's record does not give.
    """
    try:
        supports = tuple(stamped_support(one, _episode_of(one, held)) for one in memory.supports)
    except ValueError as exc:
        msg = f"refusing to write {memory.id!r}: {exc}"
        raise MemoryStoreError(msg) from exc
    if supports == memory.supports:
        return memory
    return Memory.model_validate(memory.model_dump() | {"supports": supports})


def _refuse_creating(decision: MemoryDecision, proposal: MemoryUpdateProposal) -> None:
    """Refuse a ruling that would create a memory ADR-0345 §2:4, §6:1, §8:3 or §8:4 refuses.

    An ``ACCEPT`` creates the proposed memory as it is, and a ``SUPERSEDE`` creates it
    afresh with an open window (ADR-0045 §4); a fold creates nothing, so no rule on a
    create binds it.

    Raises:
        MemoryStoreError: If the memory the ruling creates breaks one of them.
    """
    match decision.kind:
        case MemoryDecisionKind.ACCEPT:
            created = proposal.proposed
        case MemoryDecisionKind.SUPERSEDE:
            created = proposal.proposed.model_copy(update={"validity": Validity()})
        case _:
            return
    fault = created_fault(created)
    if fault is not None:
        msg = f"refusing to write {created.id!r}: {fault}"
        raise MemoryStoreError(msg)


def _refuse_created(memory: Memory, held: Mapping[str, MemoryRecord]) -> None:
    """Refuse a memory a write creates that ADR-0345 §2:4, §6:1, §8:3, §8:4 or §9:3 refuses.

    Raises:
        MemoryStoreError: If it breaks one of them.
    """
    fault = created_fault(memory)
    if fault is not None:
        msg = f"refusing to write {memory.id!r}: {fault}"
        raise MemoryStoreError(msg)
    _refuse_ungiven_names(memory, held)


def _refuse_ungiven_names(memory: Memory, held: Mapping[str, MemoryRecord]) -> None:
    """ADR-0345 §9:3, as ``MemoryIngestor`` refuses it.

    Raises:
        MemoryStoreError: If ``subjects`` or ``involved`` names someone no part gives.
    """
    episodes = {key: one for key, one in held.items() if isinstance(one, EpisodicMemory)}
    ungiven = names_not_given(memory, episodes)
    if ungiven:
        msg = f"refusing to write {memory.id!r}: {ungiven!r} named by no part (ADR-0345 §9:3)"
        raise MemoryStoreError(msg)


def _check_label_bounds(labels: Sequence[str], bounds: LabelBounds) -> None:
    """ADR-0345 §7:3: the labels a memory is written with, each one and all together.

    Raises:
        MemoryStoreError: If there are more than the bounds admit, or one is longer.
    """
    if len(labels) > bounds.max_labels:
        msg = f"refusing to write more than {bounds.max_labels} labels (ADR-0345 §7:3)"
        raise MemoryStoreError(msg)
    long = next((one for one in labels if len(one) > bounds.max_chars), None)
    if long is not None:
        msg = (
            f"refusing to write a label longer than {bounds.max_chars} characters "
            f"(ADR-0345 §7:3): {long!r}"
        )
        raise MemoryStoreError(msg)


def _cosine_distance(left: Embedding, right: Embedding) -> float:
    """The cosine distance between two vectors, ``0`` to ``2``; ``1`` where either is zero."""
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norms = sqrt(sum(a * a for a in left)) * sqrt(sum(b * b for b in right))
    return 1.0 if norms == 0.0 else 1.0 - dot / norms


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

    An observer's inference is admitted among the supports the fold actually adds
    (ADR-0329 §9:7), as ``MemoryIngestor``'s.

    Raises:
        MemoryStoreError: If ``target`` is not a memory, the supports it would add
            break §9:7 or ADR-0345 §2:4, or an add support is refused.
    """
    if not isinstance(target, Memory):
        msg = f"cannot reinforce {target.id!r}: not a memory"
        raise MemoryStoreError(msg)
    fault = inference_fault(
        [one for one in incoming.supports if target.support_at(one.points_at) is None]
    )
    if fault is not None:
        msg = f"cannot reinforce {target.id!r}: {fault}"
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
    fault = added_backing_fault(target, folded)
    if fault is not None:
        msg = f"cannot reinforce {target.id!r}: {fault}"
        raise MemoryStoreError(msg)
    return folded.model_copy(update={"placement": target.placement.folded_with(incoming.placement)})


@dataclass(frozen=True, slots=True)
class _Retiring:
    """A proposal's retiring operation, checked and ready to apply (ADR-0329 §12:4)."""

    retirement: MemoryRetirement
    cited: MemorySupport
    at: datetime
    by: MemoryWriterName

    def write(self, successor: str | None) -> MemoryWrite:
        """The retired memory's write, conditional on its revision as read (§5:4).

        Raises:
            MemoryStoreError: If ADR-0328 §4, §5 or §6:5 refuses the operation.
        """
        retired = self.retirement.memory
        try:
            record = retired_memory(
                self.retirement, self.cited, successor=successor, at=self.at, by=self.by
            )
        except ValueError as exc:
            msg = f"refusing to retire {retired.id!r}: {exc}"
            raise MemoryStoreError(msg) from exc
        return MemoryWrite(
            record=record, mode=MemoryWriteMode.IF_UNCHANGED, expected_revision=retired.revision
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
        label_bounds: LabelBounds | None = None,
        label_embedder: Embedder | None = None,
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
            label_bounds: The bounds on a memory's labels (ADR-0345 §7:3, §7:5); with
                none, the fake writes no label, as ``MemoryIngestor`` does not.
            label_embedder: The embedder a new label is compared by.
        """
        self._store = store
        self._policy = policy
        self._conflict_threshold = conflict_threshold
        self._conflict_limit = conflict_limit
        self._clock = checked_clock(now, owner="FakeMemoryWriter")
        self._id_factory = id_factory
        self._reconciler = reconciler
        self._label_bounds = label_bounds
        self._label_embedder = label_embedder
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
            MemoryStoreError: If §4, §5, §6:5 or ADR-0345 §2:4 refuses the operation.
        """
        observed = change.model_copy(deep=True)
        async with self._lock:
            memory = observed.memory
            # §4:7 binds a support actually added: one the memory already carries
            # changes nothing and is no error (§4:8), its episode gone or not.
            carried = observed.support is not None and memory.support_at(observed.support.points_at)
            added = () if observed.support is None or carried else (observed.support,)
            successor = () if observed.successor is None else observed.successor.supports
            held = await self._require_held_episodes(memory.id, (*added, *successor))
            # ADR-0345 §2:2: what the operation adds, and the successor it creates,
            # carry their holders, as ``MemoryIngestor`` sets them.
            if added:
                try:
                    stamped = stamped_support(added[0], _episode_of(added[0], held))
                except ValueError as exc:
                    msg = f"refusing to apply a {observed.operation.kind}: {exc}"
                    raise MemoryStoreError(msg) from exc
                observed = observed.model_copy(update={"support": stamped})
                added = (stamped,)
            if observed.successor is not None:
                created = _stamped(observed.successor, held)
                _refuse_created(created, held)
                _, refused = await self._admit_labels([], [one.text for one in created.labels])
                if refused:
                    msg = f"refusing to create {created.id!r}: a near-duplicate label (§7:5)"
                    raise MemoryStoreError(msg)
                observed = observed.model_copy(update={"successor": created})
                successor = created.supports
            fault = (
                added_inference_fault(added[0] if added else None)
                or inference_fault(successor)
                or inference_when_fault(successor, held)
            )
            if fault is not None:
                msg = f"refusing to apply a {observed.operation.kind} to {memory.id!r}: {fault}"
                raise MemoryStoreError(msg)
            try:
                after = applied_operation(
                    memory, observed.operation, support=observed.support, question=observed.question
                )
            except ValueError as exc:
                msg = f"refusing to apply a {observed.operation.kind} to {memory.id!r}: {exc}"
                raise MemoryStoreError(msg) from exc
            # ADR-0345 §2:4, §8:3: on what the operation adds, as ``MemoryIngestor``'s.
            fault = added_backing_fault(memory, after)
            if fault is not None:
                msg = f"refusing to apply a {observed.operation.kind} to {memory.id!r}: {fault}"
                raise MemoryStoreError(msg)
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
                        record=observed.successor,
                        mode=MemoryWriteMode.INSERT_IF_ABSENT,
                    )
                )
            await self._store.write_atomic(batch)

    async def record_use(self, memory: Memory, entry: TrackRecordEntry) -> None:
        """Record one track-record entry, as ``MemoryIngestor`` does (ADR-0329 §14:4).

        Raises:
            MemoryStoreStaleError: If the stored memory is not the one read.
            MemoryStoreError: If ``memory`` carries no revision.
        """
        observed = memory.model_copy(deep=True)
        recorded = entry.model_copy(deep=True)
        async with self._lock:
            if observed.revision < 1:
                msg = f"refusing to record a use of {observed.id!r}: it carries no revision"
                raise MemoryStoreError(msg)
            if any(one.episode == recorded.episode for one in observed.track_record):
                return
            after = Memory.model_validate(
                observed.model_dump() | {"track_record": (*observed.track_record, recorded)}
            )
            await self._store.write_atomic(
                [
                    MemoryWrite(
                        record=after,
                        mode=MemoryWriteMode.IF_UNCHANGED,
                        expected_revision=observed.revision,
                    )
                ]
            )

    async def write_labels(self, change: MemoryLabelChange) -> MemoryLabelResult:
        """Replace one stored memory's labels whole, as ``MemoryIngestor`` does (ADR-0345 §7:6).

        Raises:
            MemoryStoreStaleError: If the stored memory is not the one read.
            MemoryStoreError: If the labels break the bounds, or none were wired.
        """
        observed = change.model_copy(deep=True)
        async with self._lock:
            memory = observed.memory
            kept = {label.text: label for label in memory.labels}
            carried = [text for text in observed.labels if text in kept]
            new = [text for text in observed.labels if text not in kept]
            accepted, refused = await self._admit_labels(carried, new)
            now = self._now_utc()
            labels = tuple(
                kept[text]
                if text in kept
                else SituationLabel(
                    text=text, added_at=now, added_by=observed.by, episode=observed.episode
                )
                for text in observed.labels
                if text in kept or text in accepted
            )
            after = Memory.model_validate(memory.model_dump() | {"labels": labels})
            # Written even where the labels are those read: the write is conditional on
            # the revision read, so a memory another writer moved is refused rather than
            # reported as carrying labels it no longer carries (§7:6, ADR-0219 §2).
            await self._store.write_atomic(
                [
                    MemoryWrite(
                        record=after,
                        mode=MemoryWriteMode.IF_UNCHANGED,
                        expected_revision=memory.revision,
                    )
                ]
            )
            return MemoryLabelResult(labels=labels, refused=tuple(refused))

    async def _admit_labels(
        self, carried: Sequence[str], new: Sequence[str]
    ) -> tuple[list[str], list[str]]:
        """The new labels admitted beside those kept, and the near-duplicates (§7:3, §7:5).

        Raises:
            MemoryStoreError: If no bounds were wired, a label breaks them, or the
                embedder fails.
        """
        bounds = self._label_bounds
        if not new:
            if bounds is not None:
                _check_label_bounds(carried, bounds)
            return [], []
        embedder = self._label_embedder
        if bounds is None or embedder is None:
            msg = "refusing to write a label: no label bounds were wired (ADR-0345 §7:3)"
            raise MemoryStoreError(msg)
        if any(len(text) > bounds.max_chars for text in [*carried, *new]):
            msg = f"refusing a label longer than {bounds.max_chars} characters (ADR-0345 §7:3)"
            raise MemoryStoreError(msg)
        try:
            # Read whole inside the boundary, so a malformed element (a ``None``, a
            # non-number) is the writer's error rather than one raised comparing it.
            vectors = [
                [float(value) for value in one] for one in await embedder.embed([*carried, *new])
            ]
        except Exception as exc:  # any fault from the injected embedder is the writer's error
            msg = f"refusing to write a label: the embedder failed ({exc})"
            raise MemoryStoreError(msg) from exc
        if len(vectors) != len(carried) + len(new) or len({len(one) for one in vectors}) > 1:
            msg = "refusing to write a label: the embedder returned malformed vectors"
            raise MemoryStoreError(msg)
        held = vectors[: len(carried)]
        accepted: list[str] = []
        refused: list[str] = []
        for text, vector in zip(new, vectors[len(carried) :], strict=True):
            if any(_cosine_distance(vector, other) <= bounds.min_distance for other in held):
                refused.append(text)
                continue
            accepted.append(text)
            held.append(vector)
        _check_label_bounds([*carried, *accepted], bounds)
        return accepted, refused

    async def _labelled(self, memory: Memory) -> tuple[Memory, tuple[str, ...]]:
        """A created memory with its near-duplicate labels left out (ADR-0345 §7:5, §7:7).

        Raises:
            MemoryStoreError: If its labels break the bounds, or none were wired.
        """
        if not memory.labels:
            return memory, ()
        accepted, refused = await self._admit_labels([], [label.text for label in memory.labels])
        if not refused:
            return memory, ()
        labels = tuple(label for label in memory.labels if label.text in accepted)
        return memory.model_copy(update={"labels": labels}), tuple(refused)

    def _retiring(
        self, proposal: MemoryUpdateProposal, held: Mapping[str, MemoryRecord]
    ) -> _Retiring | None:
        """The admission refusals and the checked retirement, as ``MemoryIngestor``'s.

        Raises:
            MemoryStoreError: On an inference §9:7 forbids, or a retirement §12:4, §12:5,
                ADR-0328 §5 or §6:5 refuses.
        """
        proposed = proposal.proposed
        fault = (
            inference_fault(proposed.supports)
            or inference_when_fault(proposed.supports, held)
            or retirement_fault(proposal)
        )
        if fault is not None:
            msg = f"refusing to ingest {proposed.id!r}: {fault}"
            raise MemoryStoreError(msg)
        retirement = proposal.retiring
        if retirement is None:
            return None
        cited = proposed.support_at(retirement.cites)
        if cited is None:  # pragma: no cover - retirement_fault found it among the backing
            msg = f"refusing to ingest {proposed.id!r}: its retirement cites no support of it"
            raise MemoryStoreError(msg)
        retiring = _Retiring(
            retirement=retirement, cited=cited, at=self._now_utc(), by=proposed.operations[0].by
        )
        retiring.write(proposed.id)
        return retiring

    async def _ingest(self, observed: MemoryUpdateProposal) -> MemoryIngestResult:
        held = await self._require_held_episodes(observed.proposed.id, observed.proposed.supports)
        proposed = _stamped(observed.proposed, held)
        _refuse_ungiven_names(proposed, held)
        proposed, refused_labels = await self._labelled(proposed)
        observed = observed.model_copy(update={"proposed": proposed})
        if observed.placement is not None:
            return await self._ingest_placed(observed, refused_labels, held)
        retiring = self._retiring(observed, held)
        conflicts = await self._conflicts_for(
            observed.proposed,
            withheld=None if retiring is None else retiring.retirement.memory.id,
        )
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
        _refuse_creating(decision, observed)
        record_id = await self._apply(
            decision,
            observed,
            conflicts,
            resolved=resolved,
            relations=relations or {},
            retiring=retiring,
        )
        return MemoryIngestResult(
            decision=decision,
            record_id=record_id,
            conflicts=resolved,
            contradicted=_contradicted(decision, conflicts, relations or {}),
            refused_labels=refused_labels if record_id is not None else (),
        )

    async def _ingest_placed(
        self,
        observed: MemoryUpdateProposal,
        refused_labels: tuple[str, ...],
        held: Mapping[str, MemoryRecord],
    ) -> MemoryIngestResult:
        """A placed proposal, as ``MemoryIngestor`` writes it (ADR-0345 §4, §5).

        Raises:
            MemoryStoreError: If a ruling other than the floor's, the confirmation
                rule's or an ``ACCEPT`` arrives, or any rule refuses the write.
        """
        placement = observed.placement
        if placement is None:  # pragma: no cover - routed here only when placed
            msg = "only a placed proposal is written by its placement"
            raise MemoryStoreError(msg)
        fault = placed_fault(observed)
        if fault is not None:
            msg = f"refusing to write {observed.proposed.id!r}: {fault}"
            raise MemoryStoreError(msg)
        named = [pair.memory for pair in placement.pairs]
        found = await self._store.get_many(named) if named else {}
        read = {key: one for key, one in found.items() if isinstance(one, Memory)}
        conflicts: list[MemoryRecord] = [read[key] for key in named if key in read]
        resolved = tuple(one.id for one in conflicts)
        ruled = observed.model_copy(update={"conflicts": resolved})
        decision = await self._policy.decide(ruled, conflicts=conflicts, relations=None)
        if decision.kind in {MemoryDecisionKind.REJECT, MemoryDecisionKind.ASK_USER}:
            return MemoryIngestResult(decision=decision, conflicts=resolved)
        _refuse_before_write(decision, observed, resolved=resolved)
        # §4:7: a placement read at a revision the store no longer holds is refused
        # whole, before any ruling writes, a confirmed one's included.
        stale = tuple(
            pair.memory
            for pair in placement.pairs
            if pair.memory not in read or read[pair.memory].revision != pair.revision
        )
        if stale:
            return MemoryIngestResult(decision=decision, conflicts=resolved, stale=stale)
        if decision.kind is MemoryDecisionKind.SUPERSEDE and observed.confirmation is not None:
            record_id = await self._apply_fold(
                decision, observed, conflicts, resolved=resolved, relations={}, retiring=None
            )
            return MemoryIngestResult(decision=decision, record_id=record_id, conflicts=resolved)
        if decision.kind is not MemoryDecisionKind.ACCEPT:
            msg = (
                f"refusing a {decision.kind} ruling on a placed proposal: a policy rules on one "
                f"by its floor and its rule on a confirmed proposal alone (ADR-0345 §4:5)"
            )
            raise MemoryStoreError(msg)
        numbers = await _episode_numbers(self._store, ordered_episodes(observed.proposed), held)
        try:
            placed = placed_write(observed, read, at=self._now_utc(), numbers=numbers)
        except ValueError as exc:
            msg = f"refusing to write {observed.proposed.id!r}: {exc}"
            raise MemoryStoreError(msg) from exc
        batch = [
            MemoryWrite(
                record=after,
                mode=MemoryWriteMode.IF_UNCHANGED,
                expected_revision=read[key].revision,
            )
            for key, after in placed.changed.items()
        ]
        if placed.installed is not None:
            batch.insert(
                0, MemoryWrite(record=placed.installed, mode=MemoryWriteMode.INSERT_IF_ABSENT)
            )
        if batch:
            await self._store.write_atomic(batch)
        return MemoryIngestResult(
            decision=decision,
            record_id=placed.installed.id if placed.installed is not None else placed.folded[0],
            conflicts=resolved,
            folded=placed.folded,
            refused_labels=refused_labels if placed.installed is not None else (),
        )

    async def _relations_for(
        self, proposal: MemoryUpdateProposal, conflicts: Sequence[MemoryRecord]
    ) -> dict[str, ConflictRelation] | None:
        """The relations this writer holds for one ingest, or ``None`` (ADR-0159 §2, §3, §6)."""
        if not _may_reconcile(proposal):
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
    ) -> Mapping[str, MemoryRecord]:
        """Refuse supports pointing at an episode the store does not hold (ADR-0328 §4:7).

        Returns:
            The episodes read, by id.

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
            return {}
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
        return held

    async def _conflicts_for(
        self, memory: Memory, *, withheld: str | None = None
    ) -> list[MemoryRecord]:
        """Every conflict retrieval surfaced, or a refusal above the ceiling (ADR-0079 §1).

        ``withheld``, the memory a proposal's retiring operation retires, is never a
        conflict (ADR-0329 §12:4).

        Raises:
            MemoryStoreError: If retrieval surfaced more conflicts than this writer
                resolves in one ingest.
        """
        found = await self._store.search(
            memory.content,
            limit=self._conflict_limit + (2 if withheld is None else 3),
            kinds=[MemoryKind.MEMORY],
        )
        conflicts = [
            match
            for match in found.records
            if match.id not in {memory.id, withheld}
            and (match.score or 0.0) >= self._conflict_threshold
        ]
        if len(conflicts) > self._conflict_limit:
            msg = (
                f"refusing to ingest {memory.id!r}: conflict resolution surfaced more than "
                f"{self._conflict_limit} conflicting records (ADR-0079 §1)"
            )
            raise MemoryStoreError(msg)
        return conflicts

    async def _apply(  # noqa: PLR0913 — the ruling, what it rules on, and what the fold reads
        self,
        decision: MemoryDecision,
        proposal: MemoryUpdateProposal,
        conflicts: list[MemoryRecord],
        *,
        resolved: tuple[str, ...],
        relations: Mapping[str, ConflictRelation],
        retiring: _Retiring | None,
    ) -> str | None:
        proposed = proposal.proposed
        match decision.kind:
            case MemoryDecisionKind.ACCEPT:
                if retiring is None:
                    batch = [MemoryWrite(record=proposed, mode=MemoryWriteMode.INSERT_IF_ABSENT)]
                else:
                    # ADR-0329 §12:4: the install and the operation in one write, each
                    # naming the other (ADR-0328 §5:6).
                    installed = replaces_with(proposed, retiring.retirement.memory.id)
                    batch = [
                        MemoryWrite(record=installed, mode=MemoryWriteMode.INSERT_IF_ABSENT),
                        retiring.write(installed.id),
                    ]
                written = await self._store.write_atomic(batch)
                return written[0]
            case MemoryDecisionKind.REINFORCE | MemoryDecisionKind.SUPERSEDE:
                if retiring is not None and (
                    decision.kind is MemoryDecisionKind.SUPERSEDE
                    or retiring.retirement.kind is MemoryOperationKind.REPLACE
                ):
                    return None  # ADR-0329 §12:4: nothing is written
                return await self._apply_fold(
                    decision,
                    proposal,
                    conflicts,
                    resolved=resolved,
                    relations=relations,
                    retiring=retiring,
                )
            case _:  # REJECT, ASK_USER — nothing is written.
                return None

    async def _apply_fold(  # noqa: PLR0913 — the ruling, what it rules on, and what the fold reads
        self,
        decision: MemoryDecision,
        proposal: MemoryUpdateProposal,
        conflicts: list[MemoryRecord],
        *,
        resolved: tuple[str, ...],
        relations: Mapping[str, ConflictRelation],
        retiring: _Retiring | None,
    ) -> str | None:
        """A ``REINFORCE`` or a ``SUPERSEDE`` at its target, as ``MemoryIngestor``'s."""
        proposed = proposal.proposed
        match decision.kind:
            case MemoryDecisionKind.REINFORCE | MemoryDecisionKind.SUPERSEDE:
                target = next((c for c in conflicts if c.id == decision.target_id), None)
                if target is None:
                    msg = f"fold target {decision.target_id!r} is not among the conflicts"
                    raise MemoryStoreError(msg)
                _refuse_unsafe_fold(target, proposal, decision.kind, resolved=resolved)
                _refuse_retiring_a_related_conflict(target, decision.kind, relations)
                if decision.kind is MemoryDecisionKind.SUPERSEDE:
                    retired = _retirement_set(
                        target,
                        conflicts,
                        proposal=proposal,
                        resolved=resolved,
                        relations=relations,
                    )
                    return await self._apply_supersede(retired, proposed)
                folded = _reinforced(target, proposed, now=self._now_utc())
                written = await self._store.write_atomic(
                    [
                        MemoryWrite(
                            record=folded,
                            mode=MemoryWriteMode.IF_UNCHANGED,
                            expected_revision=target.revision,
                        ),
                        *(() if retiring is None else (retiring.write(None),)),
                    ]
                )
                return written[0]
            case _:  # pragma: no cover - only a fold reaches here
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
            successor = _supersede(proposed, new_id, retired_ids)
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
