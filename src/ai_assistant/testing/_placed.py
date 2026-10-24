"""The write a placed proposal yields, as the canonical fake writes it (ADR-0345 §3, §5).

The fake's own copy of :mod:`ai_assistant.memory._placed`, since no testing module
imports ``memory`` (golden rule 1), as :mod:`ai_assistant.testing._operations` copies
the operation a writer applies. The shared placed-write suite holds both writers to the
same records and the same refusals, so the two cannot drift unseen.

**A memory changes only in its own holder's beliefs** (§3). A retiring relation adds the
proposal's backing supports to the stored memory as ``against``, stops the counted
supports on it whose holder is a holder of one of them, each citing that holder's
backing support, and retires it exactly where nothing then backs it as worded; a memory
some other holder still holds stays current, and its remaining backing is added as
``against`` where the proposal lands, so the dispute is recorded on both (§3:5).
ADR-0328 §6:5's refusal by standing does not bind (§3:6).

**One disposition for the whole proposal** (§5:3): a ``claimed_too_much`` installs it;
otherwise a ``restates`` that would not raise the stored memory's standing, or a
``contained`` every holder of its backing already holds, folds it into each such memory
(neither, where it carries a confirmation support); and otherwise it is installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    RETIRING_RELATIONS,
    HolderKind,
    Memory,
    MemoryMark,
    MemoryOperation,
    MemoryOperationKind,
    MemoryStatus,
    MemorySupport,
    OpenQuestion,
    OpenQuestionKind,
    PlacedRelation,
    RoundMessagePart,
    SupportDirection,
    SupportOrigin,
    origin_standing,
    standing_rank,
)
from ai_assistant.testing._operations import applied_operation

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from ai_assistant.core.types import (
        MemoryPlacement,
        MemoryUpdateProposal,
        MemoryWriterName,
        PlacedPair,
        SupportHolder,
        SupportPart,
    )

__all__ = ["PlacedWrite", "backing_fault", "created_fault", "placed_fault", "placed_write"]

#: §5:10: the supports a placed proposal never carries.
_NEVER_PLACED: Final = frozenset({SupportOrigin.OBSERVER_INFERENCE, SupportOrigin.PINNED})

#: §2:4, §8:3: the marks a memory backed by the assistant's statement carries.
_RECORD_OF_SAYING: Final = frozenset({MemoryMark.ASSISTANT_STATEMENT, MemoryMark.OCCASION})


@dataclass(frozen=True, slots=True)
class PlacedWrite:
    """Everything one placed proposal writes, in one atomic write (ADR-0345 §5:6).

    Attributes:
        installed: The proposed memory as installed, or ``None`` where it was folded.
        changed: Each stored memory the write changes, by id, as it yields it.
        folded: The memories the proposal was folded into, in the placement's order.
        retired: The memories a retiring relation retired, in the placement's order.
    """

    installed: Memory | None
    changed: Mapping[str, Memory]
    folded: tuple[str, ...] = ()
    retired: tuple[str, ...] = ()


def _marked_saying(memory: Memory) -> bool:
    return _RECORD_OF_SAYING.issubset(memory.marks)


def _assistant_backed(supports: Sequence[MemorySupport]) -> bool:
    return any(
        one.holder is not None and one.holder.kind is HolderKind.ASSISTANT_STATEMENT
        for one in supports
    )


def created_fault(memory: Memory) -> str | None:
    """Which of ADR-0345's rules on a memory any write creates it breaks, if any.

    §8:3's first refusal, a memory marked ``assistant_statement`` with no support
    pointing at a round's message; §8:4's occasion with an end set at its create; and
    §6:1's future end, which a create sets only where the support it cites carries an
    about-when naming it. Bound on every create, by every path, and on no memory the
    upgrade carries (§13:4).

    §2:4's limit on what the assistant's statement backs, §8:3's second refusal, is
    :func:`backing_fault`'s, which a placed proposal is held to (:func:`placed_fault`).

    Args:
        memory: The memory a write creates.

    Returns:
        The refusal, or ``None``.
    """
    marks = set(memory.marks)
    if MemoryMark.ASSISTANT_STATEMENT in marks and not any(
        isinstance(one.points_at, RoundMessagePart) for one in memory.supports
    ):
        return (
            "a memory marked assistant_statement carries a support pointing at the round's "
            "message (ADR-0345 §8:3)"
        )
    end = memory.validity.valid_until
    if end is None:
        return None
    if MemoryMark.OCCASION in marks:
        return "a memory marked occasion carries no validity end set at its create (§8:4)"
    create = memory.operations[0]
    cited = memory.support_at(create.cites)
    if end > create.at and (cited is None or cited.about_when != end):
        return (
            "a create sets a validity end after its instant only where the support it "
            "cites carries an about-when naming that end (ADR-0345 §6:1)"
        )
    return None


def backing_fault(memory: Memory, supports: Sequence[MemorySupport]) -> str | None:
    """§2:4, §8:3: a support the assistant's statement holds backs only a record of the saying.

    Args:
        memory: The memory ``supports`` back as worded, as it is marked.
        supports: The backing supports a write adds to it, or creates it with.

    Returns:
        The refusal, or ``None`` where none of them is the assistant's or the memory is
        marked ``assistant_statement`` and ``occasion``.
    """
    if _assistant_backed(supports) and not _marked_saying(memory):
        return (
            "a support the assistant's statement holds backs only a record of the saying, "
            "marked assistant_statement and occasion (ADR-0345 §2:4, §8:3)"
        )
    return None


def placed_fault(proposal: MemoryUpdateProposal) -> str | None:
    """Which refusal a placed proposal meets before anything is read, if any.

    §5:10's supports, which no placed proposal carries, and an observer's inference
    among them, beside every rule :func:`created_fault` holds a create to.

    Args:
        proposal: The placed proposal, its supports carrying their holders.

    Returns:
        The refusal, or ``None``.
    """
    proposed = proposal.proposed
    if any(one.origin in _NEVER_PLACED for one in proposed.supports):
        return (
            "a placed proposal carries no observer_inference and no pinned support (ADR-0345 §5:10)"
        )
    return created_fault(proposed) or backing_fault(proposed, proposed.backing_supports)


def _as(  # noqa: PLR0913 — the support, and each field a relation sets on it
    support: MemorySupport,
    *,
    direction: SupportDirection,
    backs: bool,
    note: str,
    at: datetime,
    by: MemoryWriterName,
) -> MemorySupport:
    """``support`` added in a direction, backing or not, with a relation's note (§5:7)."""
    return MemorySupport.model_validate(
        support.model_dump()
        | {
            "direction": direction,
            "backs_as_worded": backs and direction is SupportDirection.FOR,
            "note": note,
            "added_at": at,
            "added_by": by,
        }
    )


@dataclass(slots=True)
class _Write:
    """The write being built: each memory it changes, and what each relation added."""

    at: datetime
    by: MemoryWriterName
    records: dict[str, Memory]
    added: dict[str, list[SupportPart]] = field(default_factory=dict)

    @staticmethod
    def apply(
        memory: Memory,
        operation: MemoryOperation,
        *,
        support: MemorySupport | None = None,
        question: OpenQuestion | None = None,
    ) -> Memory:
        """One operation, unguarded by standing (§3:6), refused as ADR-0328 §5 refuses."""
        return applied_operation(
            memory, operation, support=support, question=question, guarded=False
        )

    def add(self, memory: Memory, support: MemorySupport) -> Memory:
        """Add one support, citing it; one the memory carries already changes nothing (§4:8)."""
        if memory.support_at(support.points_at) is not None:
            return memory
        operation = MemoryOperation(
            kind=MemoryOperationKind.ADD_SUPPORT,
            cites=support.points_at,
            note=support.note,
            at=self.at,
            by=self.by,
        )
        self.added.setdefault(memory.id, []).append(support.points_at)
        return self.apply(memory, operation, support=support)

    def stop(self, memory: Memory, stopped: SupportPart, cites: SupportPart, note: str) -> Memory:
        """Stop one support counting, citing the support that explains it away (§3:3)."""
        operation = MemoryOperation(
            kind=MemoryOperationKind.STOP_COUNTING,
            cites=cites,
            note=note,
            at=self.at,
            by=self.by,
            stops=stopped,
        )
        return self.apply(memory, operation)


def _holder_cite(
    holder: SupportHolder | None, backing: Sequence[MemorySupport]
) -> SupportPart | None:
    """The proposal's backing support of the same holder as ``holder``, if any (§3:3)."""
    return next(
        (one.points_at for one in backing if one.holder is not None and one.holder.same_as(holder)),
        None,
    )


def _restates_folds(stored: Memory, proposed: Memory) -> bool:
    """§5:2: adding the proposal's supports would not raise the stored memory's standing."""
    rank = standing_rank(stored.standing)
    return all(
        standing_rank(origin_standing(one.origin)) <= rank
        for one in proposed.backing_supports
        if stored.support_at(one.points_at) is None
    )


def _folds(placement: MemoryPlacement, named: Mapping[str, Memory], proposed: Memory) -> list[str]:
    """The memories the proposal folds into under §5:3's one disposition, in order."""
    if any(pair.relation is PlacedRelation.CLAIMED_TOO_MUCH for pair in placement.pairs):
        return []
    if any(one.origin is SupportOrigin.CONFIRMATION for one in proposed.supports):
        return []
    backing = proposed.backing_supports
    folds: list[str] = []
    for pair in placement.pairs:
        stored = named[pair.memory]
        restated = pair.relation is PlacedRelation.RESTATES and _restates_folds(stored, proposed)
        contained = pair.relation is PlacedRelation.CONTAINED and all(
            one.holder is not None and stored.held_by(one.holder) for one in backing
        )
        if restated or contained:
            folds.append(pair.memory)
    return folds


def _recheck(write: _Write, stored: Memory, pair: PlacedPair) -> Memory:
    """§5:9: a ``recheck`` question resting on the stored memory's own backing, adding none."""
    rests_on = tuple(one.points_at for one in stored.backing_supports) or tuple(
        one.points_at for one in stored.supports
    )
    taken = {question.id for question in stored.open_questions}
    number = len(stored.open_questions) + 1
    while f"recheck-{number}" in taken:
        number += 1
    question = OpenQuestion(
        id=f"recheck-{number}",
        kind=OpenQuestionKind.RECHECK,
        asks=pair.note,
        rests_on=rests_on,
        raised_at=write.at,
        raised_by=write.by,
    )
    operation = MemoryOperation(
        kind=MemoryOperationKind.RAISE_QUESTION,
        cites=rests_on[0],
        note=pair.note,
        at=write.at,
        by=write.by,
        question=question.id,
    )
    return write.apply(stored, operation, question=question)


def _retire(
    write: _Write,
    stored: Memory,
    pair: PlacedPair,
    backing: Sequence[MemorySupport],
    *,
    successor: str | None,
) -> tuple[Memory, bool]:
    """§3:1-§3:4: a retiring relation, changing the stored memory in its holders' beliefs.

    Returns:
        The memory it yields, and whether it was retired.
    """
    carried = {one.points_at for one in stored.supports}
    for one in backing:
        stored = write.add(
            stored,
            _as(
                one,
                direction=SupportDirection.AGAINST,
                backs=False,
                note=pair.note,
                at=write.at,
                by=write.by,
            ),
        )
    last: SupportPart | None = None
    for one in stored.counted_supports:
        if one.points_at not in carried:
            continue
        cites = _holder_cite(one.holder, backing)
        if cites is None or cites == one.points_at:
            continue
        stored = write.stop(stored, one.points_at, cites, pair.note)
        last = cites
    kind = RETIRING_RELATIONS[pair.relation]
    retirable = stored.status is MemoryStatus.CURRENT or (
        kind is MemoryOperationKind.MARK_WRONG and stored.status is not MemoryStatus.WRONG
    )
    if stored.backing_supports or not retirable:
        return stored, False
    operation = MemoryOperation(
        kind=kind,
        cites=last if last is not None else backing[0].points_at,
        note=pair.note,
        at=write.at,
        by=write.by,
        successor=successor,
    )
    return write.apply(stored, operation), True


def _relate(  # noqa: C901, PLR0911, PLR0913 — one arm per row of §5's table
    write: _Write,
    stored: Memory,
    pair: PlacedPair,
    proposed: Memory,
    *,
    folds: Sequence[str],
    replacing: bool,
) -> Memory:
    """What §5's table writes to one stored memory, for every relation but a retiring one."""
    backing = proposed.backing_supports

    def each(
        supports: Sequence[MemorySupport], direction: SupportDirection | None, *, backs: bool
    ) -> Memory:
        nonlocal stored
        for one in supports:
            if direction is not None and one.origin is SupportOrigin.CONFIRMATION:
                # ADR-0328 §4:6, ADR-0345 §5:8: a confirmation backs only the memory it
                # confirmed, and goes elsewhere only as `against` in a dispute.
                continue
            stored = write.add(
                stored,
                _as(
                    one,
                    direction=one.direction if direction is None else direction,
                    backs=backs and one.backs_as_worded,
                    note=pair.note,
                    at=write.at,
                    by=write.by,
                ),
            )
        return stored

    match pair.relation:
        case PlacedRelation.SUPPORTS:
            return each(backing, SupportDirection.FOR, backs=False)
        case PlacedRelation.WEAKENS:
            return each(backing, SupportDirection.AGAINST, backs=False)
        case PlacedRelation.RECHECK:
            return _recheck(write, stored, pair)
        case PlacedRelation.RESTATES if pair.memory in folds:
            # §3:7: a holder's new word on the whole claim ends their own dispute with
            # it, so their `against` supports it carried before this write stop.
            carried = {one.points_at for one in stored.supports}
            stored = each(proposed.supports, None, backs=True)
            for one in stored.counted_supports:
                if one.direction is not SupportDirection.AGAINST or one.points_at not in carried:
                    continue
                cites = _holder_cite(one.holder, backing)
                if cites is not None and cites != one.points_at:
                    stored = write.stop(stored, one.points_at, cites, pair.note)
            return stored
        case PlacedRelation.CONTAINED if not replacing:
            if pair.memory in folds:
                return each(proposed.supports, None, backs=False)
            return each(backing, SupportDirection.FOR, backs=False)
        case _:
            return stored


def _resolved(write: _Write, placement: MemoryPlacement, backing: Sequence[MemorySupport]) -> None:
    """§5:5, §5:9: resolve the answered question, citing what its memory's relation added."""
    answers = placement.answers
    if answers is None:
        return
    pair = placement.relation_to(answers.memory)
    target = write.records[answers.memory]
    added = set(write.added.get(answers.memory, ()))
    cites = next((one.points_at for one in backing if one.points_at in added), None)
    if pair is None or cites is None:
        return
    operation = MemoryOperation(
        kind=MemoryOperationKind.RESOLVE_QUESTION,
        cites=cites,
        note=pair.note,
        at=write.at,
        by=write.by,
        question=answers.question,
    )
    write.records[answers.memory] = write.apply(target, operation)


def _installed(proposed: Memory, retired: Sequence[str]) -> Memory:
    """The proposed memory as installed, naming each memory it replaces (§5:4)."""
    first, *rest = proposed.operations
    create = first.model_copy(
        update={"replaces": tuple(dict.fromkeys([*first.replaces, *retired]))}
    )
    return Memory.model_validate(proposed.model_dump() | {"operations": (create, *rest)})


def _refuse_assistant_backing(original: Mapping[str, Memory], write: _Write) -> None:
    """§2:4, §8:3: no support the assistant's statement holds comes to back another memory.

    Raises:
        ValueError: If a write adds such a support, backing as worded, to a memory not
            marked both ``assistant_statement`` and ``occasion``.
    """
    for memory_id, after in write.records.items():
        added = set(write.added.get(memory_id, ()))
        newly = [one for one in after.backing_supports if one.points_at in added]
        fault = backing_fault(original.get(memory_id, after), newly)
        if fault is not None:
            msg = f"{memory_id!r}: {fault}"
            raise ValueError(msg)


def _narrowed(write: _Write, folds: Sequence[str], proposed: Memory) -> None:
    """Each memory the proposal folds into takes the placements' meet (ADR-0217 §3).

    ADR-0328 §11:9 keeps the ratchet on every fold, so a proposal narrower than the
    memory it folds into narrows that memory, and none widens it.
    """
    for memory_id in folds:
        folded = write.records[memory_id]
        write.records[memory_id] = folded.model_copy(
            update={"placement": folded.placement.folded_with(proposed.placement)}
        )


def placed_write(
    proposal: MemoryUpdateProposal, named: Mapping[str, Memory], *, at: datetime
) -> PlacedWrite:
    """Everything one placed proposal writes (ADR-0345 §3, §5).

    Args:
        proposal: The placed proposal, its supports carrying their holders.
        named: Every memory its placement names, as the writer read it at the revision
            the placement records.
        at: The write's instant.

    Returns:
        The write.

    Raises:
        ValueError: If any rule refuses it, the whole proposal with nothing written.
    """
    placement = proposal.placement
    if placement is None:  # pragma: no cover - the writer routes a placed proposal here
        msg = "only a placed proposal is written by its placement"
        raise ValueError(msg)
    fault = placed_fault(proposal)
    if fault is not None:
        raise ValueError(fault)
    proposed = proposal.proposed
    backing = proposed.backing_supports
    if not backing:
        msg = "a placed proposal rests on a counted support backing it as worded (§3:2)"
        raise ValueError(msg)
    by = proposed.operations[0].by
    replacing = any(pair.relation is PlacedRelation.CLAIMED_TOO_MUCH for pair in placement.pairs)
    folds = _folds(placement, named, proposed)
    install = replacing or not folds
    write = _Write(at=at, by=by, records=dict(named))
    retired: list[str] = []
    disputes: list[tuple[MemorySupport, str]] = []
    for pair in placement.pairs:
        stored = write.records[pair.memory]
        if pair.relation in RETIRING_RELATIONS:
            after, gone = _retire(
                write, stored, pair, backing, successor=proposed.id if install else None
            )
            if gone:
                retired.append(pair.memory)
            else:
                disputes.extend((one, pair.note) for one in after.backing_supports)
        else:
            after = _relate(write, stored, pair, proposed, folds=folds, replacing=replacing)
        write.records[pair.memory] = after
    landing = proposed if install else None
    for support, note in disputes:
        disputed = _as(
            support, direction=SupportDirection.AGAINST, backs=False, note=note, at=at, by=by
        )
        if landing is not None:
            landing = write.add(landing, disputed)
        else:
            for memory_id in folds:
                write.records[memory_id] = write.add(write.records[memory_id], disputed)
    _narrowed(write, () if install else folds, proposed)
    _resolved(write, placement, backing)
    _refuse_assistant_backing(named, write)
    changed = {
        memory_id: after for memory_id, after in write.records.items() if after != named[memory_id]
    }
    return PlacedWrite(
        installed=None if landing is None else _installed(landing, retired),
        changed=changed,
        folded=() if install else tuple(folds),
        retired=tuple(retired),
    )
