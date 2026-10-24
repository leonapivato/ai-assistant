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
write has got, and every step is put on the record through the caller as it is taken: each
``unclear`` as soon as its placement call returns (ADR-0346 §6:5); the revisions and log
lengths of what a proposal names before it is sent; and, once the write is read back, the
operations each memory's log gained, with the memory marked done in the same record. So an
attempt held by the budget or one that failed resumes where the last stopped: a memory
already done is not proposed again, and one whose proposal may have landed is read off the
store, never proposed blind. Its outcome lists the operations each memory's log gained from
the write, never one the store did not make.

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
    PlacedRelation,
    Placement,
    PlacementReach,
    PlacementSetter,
    UnclearPlacement,
)
from ai_assistant.orchestration.observer.placement import PlacementView, narrows, retrieved

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
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

#: The relations under which a placed proposal is folded into the stored memory (§5:3).
_FOLDING: Final = frozenset({PlacedRelation.RESTATES, PlacedRelation.CONTAINED})

#: The relations that write nothing on the stored memory they name (ADR-0345 §5).
_WRITES_NOTHING: Final = frozenset({PlacedRelation.INDEPENDENT, PlacedRelation.UNCLEAR})


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
                record = await self._resolved(record, ledger)
                if record.state is FramedState.DONE:
                    await keep(index, record)
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
        """Retrieve, place and propose one framed memory, again while its placement is stale."""
        base = self._base(supply, narrowing)
        for _ in range(self._limits.stale_retries + 1):
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
            view = PlacementView(framed=memory, texts=texts, retrieved=stored)
            placement = await place(view) if stored else MemoryPlacement()
            before = {one.memory.id: one.memory for one in stored}
            record = record.model_copy(
                update={
                    "state": FramedState.PROPOSING,
                    "named": tuple(
                        NamedRevision(
                            memory=pair.memory,
                            relation=pair.relation,
                            operations=len(before[pair.memory].operations),
                        )
                        for pair in placement.pairs
                    ),
                    "unclear": (*record.unclear, *_unclear(placement, memory.content)),
                }
            )
            # The unclear and what the proposal names reach the record before it is sent.
            await keep(index, record)
            proposal = MemoryUpdateProposal(
                proposed=memory, rationale=_RATIONALE, placement=placement
            )
            try:
                result = (await self._writes.write(proposal)).result
            except UnresolvedEvidenceError:
                return await self._done(index, record, keep, refused=FindingUnwritten.CHECK_FAILED)
            except SelfConsumingWriteError:
                return await self._done(index, record, keep, refused=FindingUnwritten.REFUSED)
            if result.stale:
                record = record.model_copy(update={"state": FramedState.FRAMED, "named": ()})
                continue
            return await self._ruled(index, record, result, keep, ledger)
        msg = "the observer's placement stayed stale past its count (ADR-0346 §6:7)"
        raise MemoryStoreStaleError(msg)

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

    async def _resolved(self, record: FramedMemory, ledger: _Ledger) -> FramedMemory:
        """A memory whose proposal may have landed before the last attempt stopped.

        Read off the store, never assumed (:func:`_its_write`): where it landed, its
        operations are recovered and it is done; where nothing shows it did, it is placed
        again, which a fold that changed nothing repeats harmlessly (ADR-0328 §4:8).
        """
        wanted = [record.memory.id, *(one.memory for one in record.named)]
        held = await self._memory.get_history(list(dict.fromkeys(wanted)))
        landed = _its_write(record, held)
        if landed is None:
            return record.model_copy(update={"state": FramedState.FRAMED, "named": ()})
        kept, operations = landed
        for memory_id, kinds in operations.items():
            ledger.wrote(memory_id, kinds)
        return _finished(record, ruling=MemoryDecisionKind.ACCEPT, kept=kept)

    async def _read_back(
        self, record: FramedMemory, installed: str | None, ledger: _Ledger
    ) -> None:
        """The operations each memory's log gained from the write, put in the ledger.

        Read right after the write, so nothing else has appended: the observer is the one
        writer and runs one run at a time (ADR-0345 §11:1). Each memory the placement
        named, past the log length it had when named, and the memory installed, whole. A
        pin's support added by the pin pass is the pass's write, never the finding's, so
        it is not counted.
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
                    [
                        op.kind
                        for op in now.operations[one.operations :]
                        if not isinstance(op.cites, PinPart)
                    ],
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


def _its_write(
    record: FramedMemory, held: Mapping[str, Memory]
) -> tuple[tuple[str, ...], dict[str, list[MemoryOperationKind]]] | None:
    """What a proposal wrote, read off the store on a later attempt, or ``None``.

    One placed write is one atomic write, every operation of it at one instant
    (ADR-0345 §5:6), and it came before anything else written on the memories it named,
    since the proposal was sent the moment its revisions were read. So on each memory its
    placement related to it, the first operations past the recorded log length that share
    an instant are its write's, where every one of them cites one of the proposal's own
    parts or a support the memory already carried (a ``recheck`` rests on those, §5:9);
    an operation citing anything else is another write's, and so is every later instant.
    The write's instant is the earliest such; it landed where the store holds the
    proposal's own id, installed, or where a memory it folds into carries every one of its
    supports from that instant. The installed memory's operations are its create and those
    at that instant, never one a later write made.

    Args:
        record: The memory, its proposal sent at the log lengths ``named`` records.
        held: Its own id and every memory it named, as the history read returns them.

    Returns:
        Where it is held and the operations it wrote, by memory; ``None`` where nothing
        shows it landed.
    """
    own = {one.points_at for one in record.memory.supports}
    runs: dict[str, list[MemoryOperation]] = {}
    for named in record.named:
        stored = held.get(named.memory)
        if stored is None or named.relation in _WRITES_NOTHING:
            continue
        after = [
            one
            for one in stored.operations[named.operations :]
            if not isinstance(one.cites, PinPart)
        ]
        if not after:
            continue
        instant = after[0].at
        run = list(takewhile(lambda one, at=instant: one.at == at, after))  # type: ignore[misc]
        known = own | {one.points_at for one in stored.supports if one.added_at < instant}
        if all(one.by is MemoryWriterName.OBSERVER and one.cites in known for one in run):
            runs[named.memory] = run
    at = min((run[0].at for run in runs.values()), default=None)
    mine = {memory_id: run for memory_id, run in runs.items() if run[0].at == at}
    installed = held.get(record.memory.id)
    folded = tuple(
        one.memory
        for one in record.named
        if one.relation in _FOLDING
        and one.memory in mine
        and own <= {support.points_at for support in held[one.memory].supports}
    )
    if installed is None and not folded:
        return None
    operations = {memory_id: [one.kind for one in run] for memory_id, run in mine.items()}
    if installed is not None:
        first, *rest = installed.operations
        operations[installed.id] = [first.kind, *(one.kind for one in rest if one.at == at)]
        return (installed.id,), operations
    return folded, operations


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
