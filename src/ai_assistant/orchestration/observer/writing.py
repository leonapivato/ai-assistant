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

**Where the memory is placed for** (ADR-0329 §12:6, ADR-0346 §5:7). The memory takes the
narrowest placement over every record its run was supplied, the scout's supply and the
memories retrieved for it included; and, where that leaves it placed for anyone with no
setter, the scout's proposed narrowing as a ``proposed`` placement at its create, within
ADR-0217 §4's bounds.

**A stale placement is placed again** (§6:7). Where the writer refuses the proposal as
stale (ADR-0345 §4:7), nothing was written, and code retrieves and places it again, up to
a composition-root count, within the same attempt; past it the attempt fails, and is
retried with its backoff (ADR-0329 §16:4). The pin pass runs, strictly, before each
retrieval, so a pin a person made counts in the write its memory is placed in
(ADR-0338 §9:9).

**What the policy's floor rules is final** (ADR-0345 §4:6). A ``reject`` writes nothing,
and the memory is refused; an ``ask_user`` raises nothing, and the finding's outcome
records the ask, the framed memory's wording among those asked about (ADR-0346 §6:8,
ADR-0336 §7:4).

**The outcome** names what was written, by memory, with the operations each memory's own
log gained from the write, read off it after the write, or why nothing was (ADR-0329
§16:1); every ``unclear`` a placement named, with its note and the memory it named (§6:5);
and the wordings the floor asked about. What one memory's write landed is handed to the
caller as soon as it lands, before anything else is read, so a later failure, a
cancellation or a stop loses none of it from the record.
"""

from __future__ import annotations

# At runtime, not under TYPE_CHECKING: `Landed` and `Place` are PEP 695 aliases, whose
# values are read lazily and must resolve when they are (#1706).
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import (
    MemoryStoreStaleError,
    SelfConsumingWriteError,
    UnresolvedEvidenceError,
)
from ai_assistant.core.types import (
    FindingOutcome,
    FindingUnwritten,
    MemoryDecisionKind,
    MemoryOperationKind,
    MemoryPlacement,
    MemoryUpdateProposal,
    ObservationWrite,
    PlacedRelation,
    Placement,
    PlacementReach,
    PlacementSetter,
    UnclearPlacement,
)
from ai_assistant.orchestration.observer.placement import PlacementView, retrieved

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from ai_assistant.core.protocols import MemoryStore, PlanStore
    from ai_assistant.core.types import (
        FrozenJson,
        Memory,
        MemoryIngestResult,
        ProposedNarrowing,
    )
    from ai_assistant.orchestration.observer.framing import Framed, Framing
    from ai_assistant.orchestration.observer.person import PinConfirmations
    from ai_assistant.orchestration.observer.placement import Retrieved
    from ai_assistant.orchestration.writes import MemoryWriteStage

__all__ = ["FindingWriter", "Landed", "Place", "Placed", "WriteLimits", "Written"]

#: What a commit hands its caller as each write lands: everything it has written so far,
#: by memory, in the order written (ADR-0329 §16:1).
type Landed = Callable[[tuple[ObservationWrite, ...]], Awaitable[None]]

#: The placement call, which the caller makes inside its budget and records: the
#: placement a view's reply states (ADR-0346 §6:2).
type Place = Callable[[PlacementView], Awaitable[MemoryPlacement]]

#: Why the observer proposes a memory, on every proposal it makes: code-owned words.
_RATIONALE: Final = "the observer kept this from an episode that left the episode window"


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
class Placed:
    """What became of one framed memory: what the diagnostic record shows of it.

    Attributes:
        wording: Its wording.
        relations: Each relation its placement named, by the stored memory's id.
        ruling: The policy's ruling on its proposal, where one reached the policy.
        kept: The memories it is now held at: the one installed, or those it was folded
            into; none where nothing was written.
        refused: Why the writer refused it before any ruling, where it did.
        framed: The framed memory itself.
    """

    wording: str
    relations: tuple[dict[str, FrozenJson], ...] = ()
    ruling: MemoryDecisionKind | None = None
    kept: tuple[str, ...] = ()
    refused: str | None = None
    framed: Framed | None = None

    def rendered(self) -> dict[str, FrozenJson]:
        """The memory's placement and its fate, for the outcome's diagnostic entry."""
        return {
            "wording": self.wording,
            "relations": list(self.relations),
            "ruling": None if self.ruling is None else self.ruling.value,
            "kept": list(self.kept),
            "refused": self.refused,
        }


@dataclass(frozen=True, slots=True)
class Written:
    """A finding's writes: its outcome, and what became of each framed memory."""

    outcome: FindingOutcome
    placed: tuple[Placed, ...]


@dataclass(slots=True)
class _Ledger:
    """What one finding's writes wrote, by memory, in the order written."""

    operations: dict[str, list[MemoryOperationKind]] = field(default_factory=dict)
    unclear: list[UnclearPlacement] = field(default_factory=list)
    asked: list[str] = field(default_factory=list)
    rulings: list[MemoryDecisionKind] = field(default_factory=list)
    wrote_under: MemoryDecisionKind | None = None
    reached_policy: bool = False

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
            now: The clock an outcome and a proposed narrowing are stamped from.
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

    async def write(
        self,
        framing: Framing,
        *,
        supply: Placement,
        narrowing: ProposedNarrowing | None,
        place: Place,
        landed: Landed | None = None,
    ) -> Written:
        """Place and propose each framed memory, and return the finding's outcome.

        Args:
            framing: What the framing call decided, after code's checks.
            supply: The meet over every record the run was supplied (ADR-0329 §12:6).
            narrowing: The scout's proposed narrowing (ADR-0346 §5:7).
            place: Makes the placement call for a view and returns its placement.
            landed: Handed everything written so far each time a write lands, before
                anything else is read or written (§16:1).

        Returns:
            The outcome, and what became of each framed memory.

        Raises:
            MemoryStoreStaleError: Where a placement stayed stale past the count (§6:7).
            MemoryStoreError: Where the write path failed or refused in a way only a
                retry tells apart (ADR-0329 §16:4).
        """
        ledger = _Ledger()
        placed: list[Placed] = []
        for framed in framing.memories:
            placed.append(await self._one(framed, supply, narrowing, place, ledger, landed))
        return Written(outcome=self._outcome(framing, ledger, placed), placed=tuple(placed))

    async def _one(  # noqa: PLR0913 — one framed memory, and what its write is made within
        self,
        framed: Framed,
        supply: Placement,
        narrowing: ProposedNarrowing | None,
        place: Place,
        ledger: _Ledger,
        landed: Landed | None,
    ) -> Placed:
        """Retrieve, place and propose one framed memory, again while its placement is stale."""
        wording = framed.memory.content
        for _ in range(self._limits.stale_retries + 1):
            if self._pins is not None:
                await self._pins.confirm(strict=True)
            stored = await retrieved(
                framed.memory,
                memory=self._memory,
                plans=self._plans,
                threshold=self._limits.threshold,
                bound=self._limits.bound,
                recent=self._limits.recent,
            )
            memory = framed.memory.model_copy(
                update={"placement": self._placement(supply, stored, narrowing)}
            )
            view = PlacementView(framed=memory, texts=framed.texts, retrieved=stored)
            placement = await place(view) if stored else MemoryPlacement()
            relations = _relations(placement)
            proposal = MemoryUpdateProposal(
                proposed=memory, rationale=_RATIONALE, placement=placement
            )
            try:
                result = (await self._writes.write(proposal)).result
            except UnresolvedEvidenceError:
                return Placed(wording=wording, relations=relations, refused="check_failed")
            except SelfConsumingWriteError:
                return Placed(wording=wording, relations=relations, refused="refused")
            if result.stale:
                continue
            ledger.reached_policy = True
            ledger.rulings.append(result.decision.kind)
            ledger.unclear.extend(_unclear(placement, wording))
            ruled = Placed(
                wording=wording, relations=relations, ruling=result.decision.kind, framed=framed
            )
            return await self._ruled(ruled, result, stored, ledger, landed)
        msg = "the observer's placement stayed stale past its count (ADR-0346 §6:7)"
        raise MemoryStoreStaleError(msg)

    async def _ruled(
        self,
        ruled: Placed,
        result: MemoryIngestResult,
        stored: Sequence[Retrieved],
        ledger: _Ledger,
        landed: Landed | None,
    ) -> Placed:
        """What a ruling wrote, in the ledger and handed over as it lands (§16:1)."""
        if ruled.ruling is MemoryDecisionKind.ASK_USER:
            ledger.asked.append(ruled.wording)
            return ruled
        if result.record_id is None:
            return ruled
        installed = None if result.folded else result.record_id
        ledger.wrote_under = ruled.ruling
        if installed is not None:
            ledger.wrote(installed, (MemoryOperationKind.CREATE,))
        # What landed reaches the record before anything more is read (§16:1).
        if landed is not None:
            await landed(ledger.writes())
        await self._read_back(stored, result.conflicts, installed, ledger)
        if landed is not None:
            await landed(ledger.writes())
        return replace(ruled, kept=result.folded or (result.record_id,))

    def _placement(
        self,
        supply: Placement,
        stored: Sequence[Retrieved],
        narrowing: ProposedNarrowing | None,
    ) -> Placement:
        """Where the memory is placed for (ADR-0329 §12:6, ADR-0346 §5:7)."""
        meet = Placement.narrowest_of([supply, *(one.memory.placement for one in stored)])
        if narrowing is not None and meet.reach is PlacementReach.ANYONE and meet.set_by is None:
            return Placement(
                reach=narrowing.reach, set_by=PlacementSetter.PROPOSED, set_at=self._now()
            )
        return meet

    async def _read_back(
        self,
        stored: Sequence[Retrieved],
        conflicts: Sequence[str],
        installed: str | None,
        ledger: _Ledger,
    ) -> None:
        """Each stored memory the write changed, and the operations its log gained.

        Read through the history read, so a memory the write retired is read as it now
        stands; what its log gained past the revision it was read at is what this write
        wrote on it, since the observer is the one writer and runs one run at a time
        (ADR-0345 §11:1).
        """
        before: dict[str, Memory] = {one.memory.id: one.memory for one in stored}
        wanted = [one for one in dict.fromkeys((*before, *conflicts)) if one != installed]
        if not wanted:
            return
        after = await self._memory.get_history(wanted)
        for memory_id in wanted:
            now = after.get(memory_id)
            then = before.get(memory_id)
            if now is None or then is None:
                continue
            gained = now.operations[len(then.operations) :]
            ledger.wrote(memory_id, [one.kind for one in gained])

    def _outcome(
        self, framing: Framing, ledger: _Ledger, placed: Sequence[Placed]
    ) -> FindingOutcome:
        """The finding's outcome: what was written, or why nothing was (ADR-0329 §16:1)."""
        at = self._now()
        writes = ledger.writes()
        unclear = tuple(ledger.unclear)
        asked = tuple(ledger.asked)
        if writes:
            return FindingOutcome(
                at=at, ruling=ledger.wrote_under, writes=writes, unclear=unclear, asked=asked
            )
        if asked:
            return FindingOutcome(
                at=at,
                ruling=MemoryDecisionKind.ASK_USER,
                unwritten=FindingUnwritten.ASKED,
                unclear=unclear,
                asked=asked,
            )
        ruling = ledger.rulings[-1] if ledger.rulings else None
        if not framing.memories and framing.failed == 0:
            reason = FindingUnwritten.NOT_KEPT
        elif any(one.kept for one in placed):
            reason = FindingUnwritten.ALREADY_HELD
        elif not ledger.reached_policy and not any(one.refused == "refused" for one in placed):
            reason = FindingUnwritten.CHECK_FAILED
        else:
            reason = FindingUnwritten.REFUSED
        return FindingOutcome(at=at, ruling=ruling, unwritten=reason, unclear=unclear)


def _relations(placement: MemoryPlacement) -> tuple[dict[str, FrozenJson], ...]:
    return tuple(
        {"memory": one.memory, "relation": one.relation.value, "note": one.note}
        for one in placement.pairs
    )


def _unclear(placement: MemoryPlacement, wording: str) -> list[UnclearPlacement]:
    """Every ``unclear`` a placement named, as the outcome keeps it (ADR-0346 §6:5)."""
    return [
        UnclearPlacement(memory=one.memory, wording=wording, note=one.note)
        for one in placement.pairs
        if one.relation is PlacedRelation.UNCLEAR
    ]
