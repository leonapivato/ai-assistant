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

**A holder's newer word supersedes their older one** (ADR-0348 §3). Where the write
installs the proposal, each counted ``against`` support on it whose holder backs it, from
a part before that holder's backing part in the record's order, stops counting in the same
write, citing that backing support. The record's order alone decides it (§3:2): an
earlier episode, by the store-wide number the store gave it (ADR-0283 §1), before a later
one, and within one episode its input before what its rounds made, its messages and its
digests' items by position. Where the record does not order two parts, the support keeps
counting, as a part after the backing one does (§3:3). A ``restates`` fold does the same
on the memory it leaves (ADR-0345 §3:7): a proposal's own older ``against`` it brings in
stops there too, beside the holder's disputes the memory carried before.

**One open check per memory** (ADR-0348 §4). A ``recheck`` on a memory already holding an
open ``recheck`` question raises nothing and writes nothing to it, and an answered
question is resolved citing a backing support of the proposal the memory carries once the
write is applied, whether this write added it or not.

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
    ConfirmationPart,
    EvidenceItemPart,
    HolderKind,
    InputPart,
    Memory,
    MemoryMark,
    MemoryOperation,
    MemoryOperationKind,
    MemoryStatus,
    MemorySupport,
    MessageCallPart,
    OpenQuestion,
    OpenQuestionKind,
    PlacedRelation,
    RoundMessagePart,
    SupportDirection,
    SupportOrigin,
    origin_standing,
    part_episode,
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

__all__ = [
    "SUPERSEDED_NOTE",
    "PlacedWrite",
    "added_backing_fault",
    "backing_fault",
    "created_fault",
    "holds_open_recheck",
    "ordered_episodes",
    "placed_fault",
    "placed_write",
]

#: §5:10: the supports a placed proposal never carries.
_NEVER_PLACED: Final = frozenset({SupportOrigin.OBSERVER_INFERENCE, SupportOrigin.PINNED})

#: §2:4, §8:3: the marks a memory backed by the assistant's statement carries.
_RECORD_OF_SAYING: Final = frozenset({MemoryMark.ASSISTANT_STATEMENT, MemoryMark.OCCASION})

#: ADR-0348 §3: the note on a stop a holder's newer word makes on an installed memory.
SUPERSEDED_NOTE: Final = "the same holder's later word on this claim supersedes this part"


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
    pointing at a round's message; §8:4's occasion with an end set at its create; §6:1's
    future end, which a create sets only where the support it cites carries an
    about-when naming it; and §2:4's limit on what the assistant's statement backs,
    §8:3's second refusal (:func:`backing_fault`). Bound on every create, by every path,
    and on no memory the upgrade carries (§13:4).

    Args:
        memory: The memory a write creates.

    Returns:
        The refusal, or ``None``.
    """
    return _marked_fault(memory) or backing_fault(memory, memory.backing_supports)


def _marked_fault(memory: Memory) -> str | None:
    """§8:3's first refusal, §8:4 and §6:1 on a memory a write creates."""
    marks = set(memory.marks)
    # ADR-0356 §13:3: a message call's message is read as the same kind of part.
    if MemoryMark.ASSISTANT_STATEMENT in marks and not any(
        isinstance(one.points_at, RoundMessagePart | MessageCallPart) for one in memory.supports
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

    A remember call, a round's message and an observer's inference alike: ADR-0346 §7:2
    has the observer create no inference, so §2:4's exception for one no longer binds a
    write. What the upgrade carried is never checked (§13:4), since the limit binds only
    the supports a write creates a memory with or adds to it.

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
    return created_fault(proposed)


def added_backing_fault(before: Memory, after: Memory) -> str | None:
    """§2:4, §8:3 on a write that adds supports to a stored memory.

    Only the backing supports ``after`` carries at a part ``before`` did not: a support
    the stored memory carries already, an upgraded one included, is never judged again
    (§13:4).

    Args:
        before: The stored memory, as the write read it.
        after: The same memory once the write's supports are added.

    Returns:
        The refusal, or ``None``.
    """
    added = [one for one in after.backing_supports if before.support_at(one.points_at) is None]
    return backing_fault(before, added)


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


def _within(part: SupportPart) -> tuple[int, tuple[int, ...] | None]:
    """Where ``part`` stands in its episode: its rank, and its position among its kind.

    An episode's input, and a yes, which is the input of the episode it was given in,
    come before everything its rounds made: their messages, their remember calls and
    their digests' evidence items (ADR-0348 §3:2). Among its kind, a recorded message
    stands by its position, and an evidence item by its digest's and its own; any other
    part has no position the record gives without the plan record, so it is unordered
    among its rank.
    """
    if isinstance(part, InputPart):
        return 0, None if part.message is None else (part.message,)
    if isinstance(part, ConfirmationPart):
        return 0, None
    if isinstance(part, EvidenceItemPart):
        return 1, (part.digest, part.item)
    return 1, None


def _before(earlier: SupportPart, later: SupportPart, numbers: Mapping[str, int]) -> bool:
    """Whether the record's order puts ``earlier`` before ``later`` (ADR-0348 §3:2).

    No clock reading decides it (ADR-0275 §4:9). Two episodes are ordered by the numbers
    the store gave them (ADR-0283 §1), where ``numbers`` holds both; one episode's parts
    by :func:`_within`. Where the record does not order them, neither is before the
    other.
    """
    first, second = part_episode(earlier), part_episode(later)
    if first is None or second is None:
        return False
    if first != second:
        one, other = numbers.get(first), numbers.get(second)
        return one is not None and other is not None and one < other
    (rank, place), (other_rank, other_place) = _within(earlier), _within(later)
    if rank != other_rank:
        return rank < other_rank
    return (
        type(earlier) is type(later)
        and place is not None
        and other_place is not None
        and place < other_place
    )


def _superseding(
    against: MemorySupport, backing: Sequence[MemorySupport], numbers: Mapping[str, int]
) -> SupportPart | None:
    """The backing support of ``against``'s holder its part comes before, if any (§3:1)."""
    holder = against.holder
    if holder is None:
        return None
    return next(
        (
            one.points_at
            for one in backing
            if one.holder is not None
            and one.holder.same_as(holder)
            and _before(against.points_at, one.points_at, numbers)
        ),
        None,
    )


def ordered_episodes(proposed: Memory) -> frozenset[str]:
    """The episodes whose order a placed write of ``proposed`` may read (ADR-0348 §3).

    Those of each counted ``against`` support whose holder backs ``proposed`` from
    another episode, and of that holder's backing supports: the writer reads the store's
    numbers for these alone, so a write with no such pair reads none. A dispute the write
    adds to the installed memory is never one of these, since its holder is no holder of
    the proposal's backing supports (ADR-0345 §3:3).

    Args:
        proposed: The proposed memory, its supports carrying their holders.

    Returns:
        The episodes, by id.
    """
    backing = proposed.backing_supports
    wanted: set[str] = set()
    for against in proposed.counted_supports:
        if against.direction is not SupportDirection.AGAINST or against.holder is None:
            continue
        episode = part_episode(against.points_at)
        for one in backing:
            other = part_episode(one.points_at)
            if (
                episode is not None
                and other is not None
                and other != episode
                and one.holder is not None
                and one.holder.same_as(against.holder)
            ):
                wanted.update((episode, other))
    return frozenset(wanted)


def _holder_cite(
    holder: SupportHolder | None, backing: Sequence[MemorySupport]
) -> SupportPart | None:
    """The proposal's backing support of the same holder as ``holder``, if any (§3:3)."""
    return next(
        (one.points_at for one in backing if one.holder is not None and one.holder.same_as(holder)),
        None,
    )


def _restates_folds(stored: Memory, proposed: Memory) -> bool:
    """§5:2: adding the proposal's supports would not raise the stored memory's standing.

    A fold adds the proposal's counted supports alone, so a support the proposal stopped
    counting is neither added nor weighed.
    """
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


def holds_open_recheck(memory: Memory) -> bool:
    """Whether ``memory`` already holds an open ``recheck`` question (ADR-0348 §4:1)."""
    return any(
        question.kind is OpenQuestionKind.RECHECK and not question.resolved
        for question in memory.open_questions
    )


def _recheck(write: _Write, stored: Memory, pair: PlacedPair) -> Memory:
    """§5:9: a ``recheck`` question resting on the stored memory's own backing, adding none.

    ADR-0348 §4:1: one open check per memory, so on a memory already holding an open
    ``recheck`` question it raises nothing and writes nothing.
    """
    if holds_open_recheck(stored):
        return stored
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
    numbers: Mapping[str, int],
) -> Memory:
    """What §5's table writes to one stored memory, for every relation but a retiring one.

    ``numbers`` order the episodes a fold's superseded supports are read in (ADR-0348 §3).
    """
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
            # §3:7, on the memory the write leaves: a holder's new word on the whole
            # claim ends their own dispute with it. Their `against` supports it carried
            # before this write stop; and so does each the fold brings in from the
            # proposal whose part comes before that holder's backing part, as on an
            # install (ADR-0348 §3:1), while a later one keeps counting (§3:3).
            carried = {one.points_at for one in stored.supports}
            stored = each(proposed.counted_supports, None, backs=True)
            for one in stored.counted_supports:
                if one.direction is not SupportDirection.AGAINST:
                    continue
                if one.points_at in carried:
                    cites = _holder_cite(one.holder, backing)
                    note = pair.note
                else:
                    cites = _superseding(one, backing, numbers)
                    note = SUPERSEDED_NOTE
                if cites is not None and cites != one.points_at:
                    stored = write.stop(stored, one.points_at, cites, note)
            return stored
        case PlacedRelation.CONTAINED if not replacing:
            if pair.memory in folds:
                return each(proposed.counted_supports, None, backs=False)
            return each(backing, SupportDirection.FOR, backs=False)
        case _:
            return stored


def _resolved(write: _Write, placement: MemoryPlacement, backing: Sequence[MemorySupport]) -> None:
    """§5:5, §5:9: resolve the answered question, citing a backing support its memory carries.

    ADR-0348 §4:3: a backing support of the proposal that the memory carries once the
    write is applied, whether this write added it or the memory already carried it; the
    question stays open where it carries none.
    """
    answers = placement.answers
    if answers is None:
        return
    pair = placement.relation_to(answers.memory)
    target = write.records[answers.memory]
    cites = next(
        (one.points_at for one in backing if target.support_at(one.points_at) is not None), None
    )
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


def _disputed(
    write: _Write,
    landing: Memory | None,
    folds: Sequence[str],
    disputes: Sequence[tuple[MemorySupport, str]],
) -> Memory | None:
    """§3:5: a memory left current records its backing as ``against`` where the proposal lands.

    On the installed memory, ``landing``, where it is installed, and otherwise on each
    memory it is folded into.

    Returns:
        The installed memory, with the disputes, or ``None`` where it is folded.
    """
    for support, note in disputes:
        disputed = _as(
            support,
            direction=SupportDirection.AGAINST,
            backs=False,
            note=note,
            at=write.at,
            by=write.by,
        )
        if landing is not None:
            landing = write.add(landing, disputed)
        else:
            for memory_id in folds:
                write.records[memory_id] = write.add(write.records[memory_id], disputed)
    return landing


def _superseded(write: _Write, landing: Memory, numbers: Mapping[str, int]) -> Memory:
    """ADR-0348 §3: a holder's newer word stops their own older ``against`` on the install.

    Each counted ``against`` support on the installed memory whose holder backs it, from
    a part before that holder's backing part in the record's order, stops counting,
    citing that backing support. It stays on the memory (ADR-0328 §5:8), so the history
    still shows what the holder said before, and that it no longer counts.
    """
    backing = landing.backing_supports
    for one in landing.counted_supports:
        if one.direction is not SupportDirection.AGAINST:
            continue
        cites = _superseding(one, backing, numbers)
        if cites is not None:
            landing = write.stop(landing, one.points_at, cites, SUPERSEDED_NOTE)
    return landing


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
    proposal: MemoryUpdateProposal,
    named: Mapping[str, Memory],
    *,
    at: datetime,
    numbers: Mapping[str, int] | None = None,
) -> PlacedWrite:
    """Everything one placed proposal writes (ADR-0345 §3, §5, ADR-0348 §3, §4).

    Args:
        proposal: The placed proposal, its supports carrying their holders.
        named: Every memory its placement names, as the writer read it at the revision
            the placement records.
        at: The write's instant.
        numbers: The number the store gave each episode of :func:`ordered_episodes`
            that it numbered (ADR-0283 §1), by id: the record's order across episodes
            (ADR-0348 §3:2). An episode it does not hold is ordered against no other.

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
            after = _relate(
                write,
                stored,
                pair,
                proposed,
                folds=folds,
                replacing=replacing,
                numbers=numbers or {},
            )
        write.records[pair.memory] = after
    landing = _disputed(write, proposed if install else None, folds, disputes)
    if landing is not None:
        landing = _superseded(write, landing, numbers or {})
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
