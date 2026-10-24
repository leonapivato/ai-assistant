"""The observer's writes: each framed memory placed and proposed, and the outcome.

Every write the observer makes goes through the orchestration write stage
(``MemoryWriteStage``), never to the store or a ``MemoryWriter`` directly (ADR-0329
§12:1). Under ADR-0346 every write is a placed proposal's (§6:6, ADR-0345 §4-§5): for each
memory a framing kept, code retrieves the stored memories like it (§6:1), the placement
call names its relation to each (§6:2), and the memory is proposed to
``MemoryWriter.ingest`` carrying that placement, with the revision each retrieved memory
was read at. The writer derives the write from the relations by rule: a fold, an install
beside, evidence for or against, a ``recheck`` question, a retirement in the holder's own
beliefs, an answered question. No reconciler runs and no retirement, question or support
is written by the observer itself.

**Where the memory is placed for, and what it may be placed against** (ADR-0329 §12:6,
ADR-0217 §3-§4, ADR-0346 §5:7). The memory takes the narrowest placement over every record
its run was supplied: the finding's supply, the stored memories it is placed against, and
the episodes their supports were read from to show them; and, where the finding's supply
leaves it placed for anyone with no setter, the scout's proposed narrowing as a
``proposed`` placement at its create. A stored memory that reaches more people than the
finding's supply and narrowing allow is not placed against at all: the relations a
placement names write supports, notes and questions onto the stored memory, and no
operation narrows a placement (ADR-0328 §5:2), so placing a private finding against a
wider memory would carry it to people it may not reach. Such a memory is not retrieved,
and the new memory stands beside it.

**Resumable, one memory at a time** (ADR-0329 §16:1, §16:4). What framing kept is on the
finding (:class:`~ai_assistant.core.types.FramedMemory`), each memory with how far its
write has got, and every step is put on the record through the caller as it is taken:
where the memory is placed for, before a placement call is shown anything (ADR-0329
§12:6); each ``unclear`` as soon as its placement call returns (ADR-0346 §6:5); the
placement, with the revisions and log lengths of what it names, before the proposal is
sent; and, once the write is read back, the operations each memory's log gained, with the
memory marked done in the same record. So an attempt held by the budget or one that failed
resumes where the last stopped: a memory already done is not proposed again.

**A write is never taken as landed from what the store holds** (ADR-0329 §16:4). The
store keeps no write identity (ADR-0219 §1, ADR-0328 §5:1; #3394), so a memory whose
proposal may have been sent is found by the one identity it has, its own id installed, and
otherwise its proposal is sent again exactly as it was, at the revisions it was read at.
Where nothing it names has moved since, that write is the one the last attempt would have
made, and its read-back is exact; where anything has, the writer refuses it as stale
(ADR-0345 §4:7) and the memory is placed again, which writes what the store does not yet
hold of it. Placing again what had landed adds no support twice and stops none twice
(ADR-0328 §4:8); it may ask a ``recheck`` again, and the outcome then lists what the
placing again wrote, not what the lost write did.

**A stale placement is placed again** (§6:7), up to a composition-root count within the
same attempt; past it the attempt fails and is retried with its backoff. The pin pass runs,
strictly, before each retrieval, so a pin a person made counts in the write its memory is
placed in (ADR-0338 §9:9).

**What the policy's floor rules is final** (ADR-0345 §4:6). A ``reject`` writes nothing;
an ``ask_user`` raises nothing, and the outcome records the ask (ADR-0346 §6:8, ADR-0336
§7:4).
"""

from __future__ import annotations

# At runtime, not under TYPE_CHECKING: `Progress` and `Place` are PEP 695 aliases, whose
# values are read lazily and must resolve when they are (#1706).
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from itertools import takewhile
from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import (
    MemoryStoreStaleError,
    SelfConsumingWriteError,
    UnresolvedEvidenceError,
)
from ai_assistant.core.types import (
    RETIRING_RELATIONS,
    FindingOutcome,
    FindingUnwritten,
    FramedMemory,
    FramedState,
    MemoryDecisionKind,
    MemoryOperation,
    MemoryOperationKind,
    MemoryPlacement,
    MemoryUpdateProposal,
    MemoryWriterName,
    NamedRevision,
    ObservationWrite,
    PinPart,
    PlacedPair,
    PlacedRelation,
    Placement,
    PlacementReach,
    PlacementSetter,
    SupportOrigin,
    UnclearPlacement,
)
from ai_assistant.orchestration.observer.person import PIN_NOTE
from ai_assistant.orchestration.observer.placement import (
    PlacementView,
    compacted,
    narrows,
    retrieved,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence, Set
    from datetime import datetime

    from ai_assistant.core.protocols import MemoryStore, PlanStore
    from ai_assistant.core.types import (
        FrozenJson,
        Memory,
        MemoryIngestResult,
        ProposedNarrowing,
        SupportPart,
    )
    from ai_assistant.orchestration.observer.person import PinConfirmations
    from ai_assistant.orchestration.observer.placement import Retrieved
    from ai_assistant.orchestration.writes import MemoryWriteStage

__all__ = ["FindingWriter", "Place", "Progress", "WriteLimits", "Written", "outcome_of"]

#: The placement call, which the caller makes inside its budget and records: the
#: placement a view's reply states (ADR-0346 §6:2).
type Place = Callable[[PlacementView], Awaitable[MemoryPlacement]]

#: Puts a finding's progress on its durable record: every framed memory as it now stands,
#: and every write landed so far, by memory (ADR-0329 §16:1).
type Progress = Callable[[tuple[FramedMemory, ...], tuple[ObservationWrite, ...]], Awaitable[None]]

#: Why the observer proposes a memory, on every proposal it makes: code-owned words.
_RATIONALE: Final = "the observer kept this from an episode that left the episode window"

#: The relations that write nothing on the stored memory they name (ADR-0345 §5).
_WRITES_NOTHING: Final = frozenset({PlacedRelation.INDEPENDENT, PlacedRelation.UNCLEAR})

#: What a relation writes on the memory it names, in a write that installs the proposal,
#: beside the supports it adds (ADR-0345 §3:1-§3:4, §5); a ``recheck`` raises its question
#: alone. Nothing folds in such a write, so a ``restates`` writes nothing there.
_INSTALL_MAKES: Final[dict[PlacedRelation, frozenset[MemoryOperationKind]]] = {
    **dict.fromkeys(
        (PlacedRelation.SUPPORTS, PlacedRelation.WEAKENS, PlacedRelation.CONTAINED),
        frozenset({MemoryOperationKind.ADD_SUPPORT, MemoryOperationKind.RESOLVE_QUESTION}),
    ),
    **{
        relation: frozenset(
            {
                MemoryOperationKind.ADD_SUPPORT,
                MemoryOperationKind.STOP_COUNTING,
                MemoryOperationKind.RESOLVE_QUESTION,
                kind,
            }
        )
        for relation, kind in RETIRING_RELATIONS.items()
    },
}


@dataclass(frozen=True, slots=True)
class WriteLimits:
    """The composition root's numbers a finding's writes are made within (ADR-0346 §6).

    Attributes:
        threshold: The least relevance a memory is retrieved at by its wording (§6:1).
        bound: The most memories retrieved for one framed memory (§6:1).
        recent: The most recent supports a retrieved memory is shown with (§6:2).
        stale_retries: How many times a stale placement is placed again (§6:7).
    """

    threshold: float
    bound: int
    recent: int
    stale_retries: int


@dataclass(frozen=True, slots=True)
class Written:
    """A finding's writes: every framed memory as it ended, and what was written."""

    framed: tuple[FramedMemory, ...]
    writes: tuple[ObservationWrite, ...]
    placed: tuple[dict[str, FrozenJson], ...] = ()


@dataclass(slots=True)
class _Ledger:
    """What the writes wrote, by memory, in the order written."""

    operations: dict[str, list[MemoryOperationKind]] = field(default_factory=dict)

    def wrote(self, memory: str, kinds: Sequence[MemoryOperationKind]) -> None:
        if kinds:
            self.operations.setdefault(memory, []).extend(kinds)

    def writes(self) -> tuple[ObservationWrite, ...]:
        return tuple(
            ObservationWrite(memory=memory, operations=tuple(kinds))
            for memory, kinds in self.operations.items()
            if kinds
        )


class FindingWriter:
    """Places and proposes each memory a framing kept, through the write stage (§12:1)."""

    def __init__(  # noqa: PLR0913 — the stores, the clock, the bounds and the pin pass
        self,
        *,
        writes: MemoryWriteStage,
        memory: MemoryStore,
        plans: PlanStore,
        now: Callable[[], datetime],
        limits: WriteLimits,
        pins: PinConfirmations | None = None,
    ) -> None:
        """Wire the writer.

        Args:
            writes: The write stage every write goes through.
            memory: The memory store memories are retrieved and read again from.
            plans: The plan store a retrieved support's content is read from.
            now: The clock a proposed narrowing is stamped from.
            limits: The composition root's numbers (ADR-0346 §6).
            pins: The pin pass run strictly before each retrieval (ADR-0338 §9:9),
                where the observer holds a person-model store; ``None`` where it holds
                none.
        """
        self._writes = writes
        self._memory = memory
        self._plans = plans
        self._now = now
        self._limits = limits
        self._pins = pins

    async def write(  # noqa: PLR0913 — the memories, what they rest on, and two seams
        self,
        framed: Sequence[FramedMemory],
        *,
        texts: Mapping[SupportPart, str],
        supply: Placement,
        narrowing: ProposedNarrowing | None,
        place: Place,
        progress: Progress,
    ) -> Written:
        """Bring each framed memory to done, putting every step on the record as it goes.

        Args:
            framed: The memories framing kept, as the finding's record holds them.
            texts: The text of each part the finding rests on, which a placement call is
                shown a memory's supports with.
            supply: The meet over every record the run was supplied (ADR-0329 §12:6).
            narrowing: The scout's proposed narrowing (ADR-0346 §5:7).
            place: Makes the placement call for a view and returns its placement.
            progress: Puts the framed memories and the writes so far on the record.

        Returns:
            Every framed memory, done, the writes this call read back, and each
            memory's placement for the diagnostic record.

        Raises:
            MemoryStoreStaleError: Where a placement stayed stale past the count (§6:7).
            MemoryStoreError: Where the write path failed or refused in a way only a
                retry tells apart (ADR-0329 §16:4).
        """
        records = list(framed)
        ledger = _Ledger()
        placed: list[dict[str, FrozenJson]] = []

        async def keep(index: int, record: FramedMemory) -> None:
            records[index] = record
            await progress(tuple(records), ledger.writes())

        for index in range(len(records)):
            record = records[index]
            if record.state is FramedState.PROPOSING:
                record = await self._resolved(index, record, supply, narrowing, keep, ledger)
            if record.state is not FramedState.DONE:
                record = await self._one(
                    index, record, texts, supply, narrowing, place, keep, ledger
                )
            placed.append(_rendered(record))
        return Written(framed=tuple(records), writes=ledger.writes(), placed=tuple(placed))

    async def _one(  # noqa: PLR0913 — one memory, and what its write is made within
        self,
        index: int,
        record: FramedMemory,
        texts: Mapping[SupportPart, str],
        supply: Placement,
        narrowing: ProposedNarrowing | None,
        place: Place,
        keep: Callable[[int, FramedMemory], Awaitable[None]],
        ledger: _Ledger,
    ) -> FramedMemory:
        """Retrieve, place and propose one framed memory, again while its placement is stale.

        Every attempt's supply takes in where an earlier one placed the memory for, kept on
        its record, so what an earlier placement call was shown narrows every later one,
        within the attempt and after a restart (ADR-0329 §12:6, ADR-0217 §3).
        """
        for _ in range(self._limits.stale_retries + 1):
            base = self._base(_carried(supply, record.memory.placement), narrowing)
            if self._pins is not None:
                await self._pins.confirm(strict=True)
            found = await retrieved(
                record.memory,
                memory=self._memory,
                plans=self._plans,
                threshold=self._limits.threshold,
                bound=self._limits.bound,
                recent=self._limits.recent,
            )
            # ADR-0217 §3: a memory reaching more people than everything this one is
            # supplied may is never placed against, since what a relation writes onto
            # it is never narrowed.
            stored, placed_for = _placeable(base, found)
            memory = record.memory.model_copy(update={"placement": placed_for})
            if stored and memory != record.memory:
                # §12:6: where the call's records place it for reaches the record before
                # the call is made, so a call that fails narrows every later attempt.
                record = record.model_copy(update={"memory": memory})
                await keep(index, record)
            view = PlacementView(framed=memory, texts=texts, retrieved=stored)
            placement = await place(view) if stored else MemoryPlacement()
            before = {one.memory.id: one.memory for one in stored}
            record = record.model_copy(
                update={
                    "memory": memory,
                    "state": FramedState.PROPOSING,
                    "named": tuple(
                        NamedRevision(
                            memory=pair.memory,
                            revision=pair.revision,
                            relation=pair.relation,
                            operations=len(before[pair.memory].operations),
                            note=pair.note,
                        )
                        for pair in placement.pairs
                    ),
                    "answers": placement.answers,
                    "unclear": (*record.unclear, *_unclear(placement, memory.content)),
                }
            )
            # The unclear and the placement reach the record before the proposal is sent.
            await keep(index, record)
            sent = await self._send(index, record, keep, ledger)
            if sent is not None:
                return sent
            record = _unsent(record)
        msg = "the observer's placement stayed stale past its count (ADR-0346 §6:7)"
        raise MemoryStoreStaleError(msg)

    async def _send(
        self,
        index: int,
        record: FramedMemory,
        keep: Callable[[int, FramedMemory], Awaitable[None]],
        ledger: _Ledger,
    ) -> FramedMemory | None:
        """Send the proposal the record holds, and the memory done; ``None`` where stale.

        The proposal is built from the record alone, so the one a later attempt sends
        again is exactly the one this attempt sent.
        """
        proposal = MemoryUpdateProposal(
            proposed=record.memory, rationale=_RATIONALE, placement=_sent(record)
        )
        try:
            result = (await self._writes.write(proposal)).result
        except UnresolvedEvidenceError:
            return await self._done(index, record, keep, refused=FindingUnwritten.CHECK_FAILED)
        except SelfConsumingWriteError:
            return await self._done(index, record, keep, refused=FindingUnwritten.REFUSED)
        if result.stale:
            return None
        return await self._ruled(index, record, result, keep, ledger)

    def _base(self, supply: Placement, narrowing: ProposedNarrowing | None) -> Placement:
        """The finding's supply, narrowed by the scout's proposal where nothing narrowed it."""
        if (
            narrowing is not None
            and supply.reach is PlacementReach.ANYONE
            and supply.set_by is None
        ):
            return Placement(
                reach=narrowing.reach, set_by=PlacementSetter.PROPOSED, set_at=self._now()
            )
        return supply

    async def _ruled(
        self,
        index: int,
        record: FramedMemory,
        result: MemoryIngestResult,
        keep: Callable[[int, FramedMemory], Awaitable[None]],
        ledger: _Ledger,
    ) -> FramedMemory:
        """What a ruling wrote, read back off the store, and the memory done (§16:1)."""
        kind = result.decision.kind
        if kind is MemoryDecisionKind.ASK_USER:
            return await self._done(index, record, keep, ruling=kind, asked=True)
        if result.record_id is None:
            return await self._done(index, record, keep, ruling=kind)
        installed = None if result.folded else result.record_id
        await self._read_back(record, installed, ledger)
        return await self._done(
            index, record, keep, ruling=kind, kept=result.folded or (result.record_id,)
        )

    async def _resolved(  # noqa: PLR0913 — the memory, what it is made within, two seams
        self,
        index: int,
        record: FramedMemory,
        supply: Placement,
        narrowing: ProposedNarrowing | None,
        keep: Callable[[int, FramedMemory], Awaitable[None]],
        ledger: _Ledger,
    ) -> FramedMemory:
        """A memory whose proposal may have been sent before the last attempt stopped.

        Never taken as landed from what the store holds (ADR-0329 §16:4). Its own id
        installed is the one identity a write leaves, so where it is held the write landed
        and its operations are recovered (:func:`_its_install`). Otherwise the same
        proposal is sent again at the revisions it was read at: the writer writes it where
        nothing it names has moved, and refuses it as stale where anything has (ADR-0345
        §4:7), and then it is placed again. It is sent again only within what its run is
        supplied now (ADR-0329 §12:6, ADR-0217 §3): the finding's supply, the memories it
        names and the episodes read to show them, each as it stands now. Where that meet
        places it for fewer people than the proposal was made for, or a memory it names
        would now reach more than the meet, it is placed again instead.

        Returns:
            The memory done, or back to framed, to be placed again.
        """
        wanted = [record.memory.id, *(one.memory for one in record.named)]
        held = await self._memory.get_history(list(dict.fromkeys(wanted)))
        installed = held.get(record.memory.id)
        if installed is not None:
            for memory_id, run in _its_install(record, installed, held).items():
                ledger.wrote(memory_id, [one.kind for one in run])
            return await self._done(
                index, record, keep, ruling=MemoryDecisionKind.ACCEPT, kept=(installed.id,)
            )
        named = [held[one.memory] for one in record.named if one.memory in held]
        if len(named) != len(record.named):
            return _unsent(record)
        shown = await compacted(
            named, memory=self._memory, plans=self._plans, recent=self._limits.recent
        )
        sent_for = record.memory.placement
        base = self._base(_carried(supply, sent_for), narrowing)
        placeable, now = _placeable(base, shown)
        if len(placeable) != len(shown) or (now.reach, now.set_by) != (
            sent_for.reach,
            sent_for.set_by,
        ):
            return _unsent(record)
        if self._pins is not None:
            await self._pins.confirm(strict=True)
        sent = await self._send(index, record, keep, ledger)
        return _unsent(record) if sent is None else sent

    async def _read_back(
        self, record: FramedMemory, installed: str | None, ledger: _Ledger
    ) -> None:
        """The operations each memory's log gained from the write, put in the ledger.

        Read right after the write, so nothing else has appended: the observer is the one
        writer and runs one run at a time (ADR-0345 §11:1). Each memory the placement
        named, past the log length it had when named, and the memory installed, whole. A
        pin's support added by the pin pass is the pass's write, never the finding's, so
        it is not counted; any other operation citing a pin is the write's (a ``recheck``
        rests on the stored memory's backing, a pin's support among it, ADR-0345 §5:9,
        and a dispute copies that backing as ``against``, §3:5).
        """
        wanted = [
            *(one.memory for one in record.named),
            *([] if installed is None else [installed]),
        ]
        if not wanted:
            return
        after = await self._memory.get_history(list(dict.fromkeys(wanted)))
        if installed is not None and (held := after.get(installed)) is not None:
            ledger.wrote(installed, [one.kind for one in held.operations])
        for one in record.named:
            now = after.get(one.memory)
            if now is not None:
                ledger.wrote(
                    one.memory,
                    [op.kind for op in now.operations[one.operations :] if not _pin_pass(op)],
                )

    async def _done(  # noqa: PLR0913 — the memory, the seam, and what its ruling says
        self,
        index: int,
        record: FramedMemory,
        keep: Callable[[int, FramedMemory], Awaitable[None]],
        *,
        ruling: MemoryDecisionKind | None = None,
        kept: tuple[str, ...] = (),
        asked: bool = False,
        refused: FindingUnwritten | None = None,
    ) -> FramedMemory:
        """The memory done, put on the record with what its write wrote, in one write."""
        done = _finished(record, ruling=ruling, kept=kept, asked=asked, refused=refused)
        await keep(index, done)
        return done


def _finished(
    record: FramedMemory,
    *,
    ruling: MemoryDecisionKind | None,
    kept: tuple[str, ...] = (),
    asked: bool = False,
    refused: FindingUnwritten | None = None,
) -> FramedMemory:
    return record.model_copy(
        update={
            "state": FramedState.DONE,
            "ruling": ruling,
            "kept": kept,
            "asked": asked,
            "refused": refused,
        }
    )


def _unsent(record: FramedMemory) -> FramedMemory:
    """``record`` back to framed, its last placement dropped, to be placed again."""
    return record.model_copy(update={"state": FramedState.FRAMED, "named": (), "answers": None})


def _sent(record: FramedMemory) -> MemoryPlacement:
    """The placement the record's proposal is sent with, as its last placement made it."""
    return MemoryPlacement(
        pairs=tuple(
            PlacedPair(
                memory=one.memory, revision=one.revision, relation=one.relation, note=one.note
            )
            for one in record.named
        ),
        answers=record.answers,
    )


def _its_install(
    record: FramedMemory, installed: Memory, held: Mapping[str, Memory]
) -> dict[str, list[MemoryOperation]]:
    """What a proposal found installed wrote, by memory, as far as the store establishes it.

    Its own id installed shows the one atomic write landed (ADR-0345 §5:6), so the store
    holds every effect of it, and what is read here is only which operations to list:
    those whose being this write's the store establishes (ADR-0329 §16:1, as the reading
    ruled on this PR has it). The write was made at the revisions it read (ADR-0219 §2), so
    on each memory the placement names its operations are the first past the log length
    recorded when the proposal was sent, at the write's one instant. Two operations
    establish that instant:

    - a support the write's relation adds, citing one of the parts it adds there: a part a
      memory carries is never added to it again (ADR-0328 §4:8), so whichever write added
      it past that length, it was this one, which would have;
    - on a memory it asks to be rechecked, the first operation past that length, the
      question every such write raises (ADR-0345 §5:9).

    At that instant, each memory's leading operations of a kind its relation makes in a
    write that installs, in its note (§5:7) and citing one of the proposal's parts, and
    the installed memory's disputes, in a retiring relation's note, citing a support of the
    memory that relation named (§3:5), are listed with the create. Where nothing
    establishes the instant, the create alone is: telling the write's other operations
    from a later write's that left the same stamps needs a write identity the store does
    not keep (#3394).

    Args:
        record: The memory, its proposal sent with the pairs ``named`` records.
        installed: The memory as installed, with its whole log.
        held: Every memory the placement named, as the history read returns them.

    Returns:
        The operations the write made, by memory.
    """
    replacing = any(one.relation is PlacedRelation.CLAIMED_TOO_MUCH for one in record.named)
    backing = record.memory.backing_supports
    # ADR-0328 §4:6, ADR-0345 §5:8: a confirmation is added elsewhere only as `against`.
    added_for = {one.points_at for one in backing if one.origin is not SupportOrigin.CONFIRMATION}
    added_against = {one.points_at for one in backing}
    runs: dict[str, list[MemoryOperation]] = {}
    instants: set[datetime] = set()
    disputed: set[SupportPart] = set()
    for named in record.named:
        stored = held.get(named.memory)
        if stored is None:
            continue
        after = stored.operations[named.operations :]
        if named.relation is PlacedRelation.RECHECK:
            run = [
                one
                for one in after[:1]
                if one.kind is MemoryOperationKind.RAISE_QUESTION
                and one.by is MemoryWriterName.OBSERVER
                and one.note == named.note
            ]
            instants.update(one.at for one in run)
            runs[named.memory] = run
            continue
        makes = _INSTALL_MAKES.get(named.relation, frozenset())
        if named.relation is PlacedRelation.CONTAINED and replacing:
            makes = frozenset()
        if not makes:
            continue
        retiring = named.relation in RETIRING_RELATIONS
        if retiring:
            disputed.update(one.points_at for one in stored.supports)
        adds = added_against if retiring else added_for
        run = _its_run(after, _made_by(named, makes, added_against))
        instants.update(
            one.at
            for one in run
            if one.kind is MemoryOperationKind.ADD_SUPPORT and one.cites in adds
        )
        runs[named.memory] = run
    create = installed.operations[0]
    if len(instants) != 1:
        return {installed.id: [create]}
    (at,) = instants
    notes = {one.note for one in record.named if one.relation in RETIRING_RELATIONS}
    own = _its_run(
        installed.operations[1:],
        lambda one: (
            one.kind is MemoryOperationKind.ADD_SUPPORT
            and one.note in notes
            and one.cites in disputed
        ),
    )
    operations = {key: run for key, run in runs.items() if run and run[0].at == at}
    operations[installed.id] = [create, *(own if own and own[0].at == at else ())]
    return operations


def _made_by(
    named: NamedRevision, makes: frozenset[MemoryOperationKind], parts: Set[SupportPart]
) -> Callable[[MemoryOperation], bool]:
    """Whether an operation is one ``named``'s relation makes, in its note, citing ``parts``."""

    def made(one: MemoryOperation) -> bool:
        return one.kind in makes and one.note == named.note and one.cites in parts

    return made


def _its_run(
    operations: Sequence[MemoryOperation], made: Callable[[MemoryOperation], bool]
) -> list[MemoryOperation]:
    """The leading ``operations`` one write made: the observer's, at one instant, each ``made``."""
    if not operations:
        return []
    first = operations[0].at
    return list(
        takewhile(
            lambda one: one.at == first and one.by is MemoryWriterName.OBSERVER and made(one),
            operations,
        )
    )


def _pin_pass(operation: MemoryOperation) -> bool:
    """Whether ``operation`` is the pin pass's: a pin's support added (ADR-0338 §9:9).

    Told by the pass's code-owned note, so a pin's support a placed write copies as
    ``against`` in a dispute (ADR-0345 §3:5, §3:8), which carries its relation's note,
    is the write's.
    """
    return (
        operation.kind is MemoryOperationKind.ADD_SUPPORT
        and isinstance(operation.cites, PinPart)
        and operation.note == PIN_NOTE
    )


def _carried(supply: Placement, earlier: Placement) -> Placement:
    """The finding's supply, narrowed by where an earlier attempt placed the memory for."""
    if earlier == Placement():
        return supply
    return Placement.narrowest_of([supply, earlier])


def _placement(base: Placement, stored: Sequence[Retrieved]) -> Placement:
    """Where the memory is placed for: the meet over everything its run was supplied."""
    return Placement.narrowest_of(
        [
            base,
            *(one.memory.placement for one in stored),
            *(supplied for one in stored for supplied in one.supplied),
        ]
    )


def _placeable(
    base: Placement, found: Sequence[Retrieved]
) -> tuple[tuple[Retrieved, ...], Placement]:
    """The stored memories a memory may be placed against, and where it is placed for.

    The meet over everything the placement would be supplied — the finding's supply, the
    memories retrieved and the episodes their shown supports were read from — and only
    the memories that meet would not narrow, since a relation writes onto them and no
    operation narrows a placement (ADR-0217 §3, ADR-0328 §5:2). A memory left out
    supplies nothing, so the meet is taken again over those kept, until nothing more is
    left out: a meet over fewer records is never narrower, so every memory kept stays
    one it may write onto.
    """
    kept = list(found)
    while True:
        meet = _placement(base, kept)
        placeable = [one for one in kept if not narrows(meet, one.memory)]
        if len(placeable) == len(kept):
            return _relabelled(placeable), meet
        kept = placeable


def _relabelled(stored: Sequence[Retrieved]) -> tuple[Retrieved, ...]:
    """The memories kept, labelled ``M1`` onward again, their questions ``Q1`` onward."""
    relabelled: list[Retrieved] = []
    asked = 0
    for number, one in enumerate(stored, start=1):
        questions: dict[str, str] = {}
        for question in one.questions.values():
            asked += 1
            questions[f"Q{asked}"] = question
        relabelled.append(replace(one, handle=f"M{number}", questions=questions))
    return tuple(relabelled)


def _unclear(placement: MemoryPlacement, wording: str) -> list[UnclearPlacement]:
    """Every ``unclear`` a placement named, as the outcome keeps it (ADR-0346 §6:5)."""
    return [
        UnclearPlacement(memory=one.memory, wording=wording, note=one.note)
        for one in placement.pairs
        if one.relation is PlacedRelation.UNCLEAR
    ]


def _rendered(record: FramedMemory) -> dict[str, FrozenJson]:
    """One memory's placement and its fate, for the outcome's diagnostic entry."""
    return {
        "wording": record.memory.content,
        "relations": [
            {"memory": one.memory, "relation": one.relation.value} for one in record.named
        ],
        "ruling": None if record.ruling is None else record.ruling.value,
        "kept": list(record.kept),
        "refused": None if record.refused is None else record.refused.value,
        "unclear": [one.model_dump(mode="json") for one in record.unclear],
    }


def outcome_of(
    framed: Sequence[FramedMemory], writes: Sequence[ObservationWrite], *, at: datetime
) -> FindingOutcome:
    """A finding's outcome from its framed memories, all done, and what they wrote.

    What was written, by memory, or why nothing was (ADR-0329 §16:1); every ``unclear``
    the placement calls named (ADR-0346 §6:5); and each wording the floor asked about
    (§6:8). Where framing kept nothing, nothing was kept; where every memory failed a
    check before any ruling, the check failed; where one folded into a memory already
    holding it, it is held already.

    Args:
        framed: Every memory framing kept, each done.
        writes: Everything written, by memory, the earlier attempts' included.
        at: When the outcome is decided.

    Returns:
        The outcome.
    """
    unclear = tuple(dict.fromkeys(one for record in framed for one in record.unclear))
    asked = tuple(record.memory.content for record in framed if record.asked)
    rulings = [record.ruling for record in framed if record.ruling is not None]
    if writes:
        wrote = next(
            (record.ruling for record in reversed(framed) if record.kept and record.ruling),
            rulings[-1] if rulings else None,
        )
        return FindingOutcome(
            at=at, ruling=wrote, writes=tuple(writes), unclear=unclear, asked=asked
        )
    if asked:
        return FindingOutcome(
            at=at,
            ruling=MemoryDecisionKind.ASK_USER,
            unwritten=FindingUnwritten.ASKED,
            unclear=unclear,
            asked=asked,
        )
    ruling = rulings[-1] if rulings else None
    if not framed:
        reason = FindingUnwritten.NOT_KEPT
    elif any(record.kept for record in framed):
        reason = FindingUnwritten.ALREADY_HELD
    elif not rulings and all(record.refused is FindingUnwritten.CHECK_FAILED for record in framed):
        reason = FindingUnwritten.CHECK_FAILED
    else:
        reason = FindingUnwritten.REFUSED
    return FindingOutcome(at=at, ruling=ruling, unwritten=reason, unclear=unclear)
