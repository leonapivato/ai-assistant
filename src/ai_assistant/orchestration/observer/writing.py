"""The observer's writes, through the write stage, and each one's outcome (ADR-0329 §12-§14).

Every write the observer makes goes through the orchestration write stage
(``MemoryWriteStage``), never to the store or a ``MemoryWriter`` directly (§12:1):

- **a new memory** is proposed through ``ingest`` and ruled on by ``MemoryPolicy``
  (§12:2), carrying the one retiring operation a finding that ends, marks wrong or
  replaces a stored memory makes (§12:4);
- **supports added** to a memory that already states the claim as worded are one add
  support each, through ``apply`` (§12:3);
- **an open question** is raised, or resolved, by that same member (§12:3, §13);
- **a track-record entry** is recorded through ``record_use``, conditionally on the
  revision read (§14:4).

Each memory written on is read again just before its write, and the write is made only
where the memory still stands at the revision the commit step decided on, or at the one
this finding's own last write left it at; otherwise the attempt fails as stale and the
finding is decided again on a retry (ADR-0219 §2-§3). Every write adds to the record and
none removes anything (§12:7): a support already on a memory changes nothing (ADR-0328
§4:8), and it is recorded as its add support, so a finding processed again after a clear
says what the memory carries rather than nothing; an entry the memory already holds for
the episode is recorded as the one held (ADR-0328 §8:3).

**The outcome** names what was written, with the memory ids and the operations, or why
nothing was (§16:1). A ruling that writes nothing is ``refused``; an ``ASK_USER`` ruling
raises a ``policy_ask`` question on each stored memory it names (§13:1), and one that
names none writes nothing and is ``asked`` (§13:3) — never logged and dropped (§13:6).
A write the writer refuses as self-consuming or as a fold onto a record it cites is
``refused`` (§12:5), and one whose part points at an episode the store no longer holds
failed §9:5's check. Every other failure of the write path fails the attempt, which is
retried and in the end set aside as stuck (§16:4-§16:5): ``MemoryStoreError`` is a
store's failure as well as a refusal, and only a retry tells a passing outage from a
refusal, so neither is recorded as a terminal outcome. What one finding wrote before a
later write of its own failed is recorded with it, never lost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import (
    MemoryStoreStaleError,
    SelfConsumingWriteError,
    UnresolvedEvidenceError,
)
from ai_assistant.core.types import (
    FindingOutcome,
    FindingUnwritten,
    Memory,
    MemoryChange,
    MemoryDecisionKind,
    MemoryOperation,
    MemoryOperationKind,
    MemoryRetirement,
    MemoryUpdateProposal,
    MemoryWriterName,
    ObservationWrite,
    OpenQuestion,
    OpenQuestionKind,
)
from ai_assistant.orchestration.observer.commit import (
    AddSupports,
    Blocked,
    Checked,
    Create,
    RaiseQuestion,
    RecordUse,
    Resolve,
    Unwritten,
    narrows,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from datetime import datetime

    from ai_assistant.core.protocols import MemoryStore
    from ai_assistant.core.types import (
        MemoryIngestResult,
        MemorySupport,
        Placement,
        TrackRecordEntry,
    )
    from ai_assistant.orchestration.writes import MemoryWriteStage

__all__ = ["FindingWriter", "WriteBlocked"]

#: What a ``policy_ask`` question asks, in words, before the claim the policy asked about.
_ASK_ASKS: Final = "The write path asked before keeping this beside this memory: "


class WriteBlocked(Exception):  # noqa: N818 — a control-flow signal the stage turns into a retry
    """A write the supply's placement keeps off a wider memory (§12:6): retried until stuck.

    Attributes:
        partial: What the finding wrote before it was blocked.
    """

    def __init__(self, partial: tuple[ObservationWrite, ...] = ()) -> None:
        """Carry what was written before the block."""
        super().__init__("placement")
        self.partial = partial


class _Refusal(Exception):  # noqa: N818 — a control-flow signal carrying a code-owned reason
    def __init__(self, reason: FindingUnwritten) -> None:
        super().__init__(reason.value)
        self.reason = reason


class _Ledger:
    """What one finding's commit wrote, by memory, in the order written."""

    def __init__(self) -> None:
        self.operations: dict[str, list[MemoryOperationKind]] = {}
        self.track_record: dict[str, bool] = {}
        self.ruling: MemoryDecisionKind | None = None

    def wrote(self, memory: str, *kinds: MemoryOperationKind) -> None:
        self.operations.setdefault(memory, []).extend(kinds)

    def recorded(self, memory: str, *, held_up: bool) -> None:
        self.operations.setdefault(memory, [])
        self.track_record[memory] = held_up

    def writes(self) -> tuple[ObservationWrite, ...]:
        """What was written so far, by memory."""
        return tuple(
            ObservationWrite(
                memory=memory,
                operations=tuple(kinds),
                track_record=self.track_record.get(memory),
            )
            for memory, kinds in self.operations.items()
        )

    def outcome(self, at: datetime, unwritten: FindingUnwritten | None) -> FindingOutcome:
        writes = tuple(
            ObservationWrite(
                memory=memory,
                operations=tuple(kinds),
                track_record=self.track_record.get(memory),
            )
            for memory, kinds in self.operations.items()
        )
        if writes:
            return FindingOutcome(at=at, ruling=self.ruling, writes=writes)
        return FindingOutcome(
            at=at, ruling=self.ruling, unwritten=unwritten or FindingUnwritten.REFUSED
        )


class FindingWriter:
    """Writes one checked commit decision through the write stage (§12:1)."""

    def __init__(
        self,
        *,
        writes: MemoryWriteStage,
        memory: MemoryStore,
        now: Callable[[], datetime],
        mint: Callable[[], str],
    ) -> None:
        """Wire the writer.

        Args:
            writes: The write stage every write goes through.
            memory: The memory store a memory is read again from before it is written.
            now: The clock an operation, a question and an outcome are stamped from.
            mint: Mints a fresh id for a question.
        """
        self._writes = writes
        self._memory = memory
        self._now = now
        self._mint = mint
        self._expected: dict[str, int] = {}
        self._shown: dict[str, Memory] = {}
        self.partial: tuple[ObservationWrite, ...] = ()

    async def write(self, checked: Checked, *, shown: Sequence[Memory] = ()) -> FindingOutcome:
        """Write ``checked`` and return the finding's outcome (§16:1).

        Args:
            checked: The decision, after code's checks.
            shown: The memories the commit step was shown, as read, against which a
                fold onto one of them is verified as this finding's own.

        Returns:
            What was written, or why nothing was.

        Raises:
            MemoryStoreStaleError: Where a memory moved between the read the decision
                was made on and its write, so the attempt is retried (§16:4).
            MemoryStoreError: Where the write path failed or refused in a way only a
                retry tells apart (§16:4).
        """
        ledger = _Ledger()
        self._expected = {}
        self._shown = {one.id: one for one in shown}
        self.partial = ()
        unwritten: FindingUnwritten | None = None
        try:
            try:
                unwritten = await self._primary(checked.primary, ledger)
            except _Refusal as refusal:
                unwritten = refusal.reason
            if checked.resolve is not None:
                try:
                    await self._resolve(checked.resolve, ledger)
                except _Refusal as refusal:
                    unwritten = unwritten or refusal.reason
        except BaseException:
            # What was written before the failure is the caller's to keep (§16:1).
            self.partial = ledger.writes()
            raise
        return ledger.outcome(self._now(), unwritten)

    async def _primary(
        self,
        primary: Create | AddSupports | RaiseQuestion | RecordUse | Unwritten | Blocked,
        ledger: _Ledger,
    ) -> FindingUnwritten | None:
        match primary:
            case Unwritten(reason=reason):
                return reason
            case Blocked():
                raise WriteBlocked
            case Create():
                return await self._create(primary, ledger)
            case AddSupports():
                target = await self._fresh(primary.target)
                for support in primary.supports:
                    await self._apply(target, MemoryOperationKind.ADD_SUPPORT, support, ledger)
                    target = await self._fresh(primary.target)
                return None
            case RaiseQuestion():
                await self._raise(
                    primary.target, primary.kind, primary.asks, primary.support, ledger
                )
                return None
            case RecordUse():
                memory = await self._fresh(primary.memory)
                entry = primary.entry
                held = next(
                    (one for one in memory.track_record if one.episode == entry.episode), None
                )
                if held is not None:
                    ledger.recorded(memory.id, held_up=held.held_up)
                    return None
                await self._guarded(
                    self._writes.record_use(memory, entry),
                    {memory.id: (memory, lambda after: _recorded(memory, after, entry))},
                    lambda: ledger.recorded(memory.id, held_up=entry.held_up),
                )
                return None

    async def _create(self, create: Create, ledger: _Ledger) -> FindingUnwritten | None:
        """§12:2, §12:4: one proposal to ``ingest``, and what its ruling wrote."""
        retiring = create.retiring
        if retiring is not None:
            retiring = MemoryRetirement(
                memory=await self._fresh(retiring.memory),
                kind=retiring.kind,
                cites=retiring.cites,
                note=retiring.note,
            )
        proposal = MemoryUpdateProposal(
            proposed=create.memory, rationale=create.rationale, retiring=retiring
        )
        checks: dict[str, tuple[Memory, Callable[[Memory], bool]]] = {}
        if retiring is not None:
            before = retiring.memory
            checks[before.id] = (before, lambda after: _retired(before, after, retiring.kind))
        outcome = await self._guarded(self._writes.write(proposal), {})
        result = outcome.result
        ledger.ruling = result.decision.kind
        # What the ruling wrote is in the ledger before anything is verified, so a
        # verification that fails still leaves it to be recorded (§16:1).
        unwritten = await self._ruled(create, retiring, result, ledger)
        target = None if result.record_id is None else self._shown.get(result.record_id)
        if target is not None and result.decision.kind is MemoryDecisionKind.REINFORCE:
            checks[target.id] = (target, lambda after: _reinforced(target, after, create.memory))
        await self._verified(checks)
        return unwritten

    async def _ruled(
        self,
        create: Create,
        retiring: MemoryRetirement | None,
        result: MemoryIngestResult,
        ledger: _Ledger,
    ) -> FindingUnwritten | None:
        """What a ruling wrote (§12:4, ADR-0328 §11:5-§11:8), or §13's question it raises."""
        kind = result.decision.kind
        if kind is MemoryDecisionKind.ASK_USER:
            return await self._asked(create, result, ledger)
        written = result.record_id
        if written is None or kind not in {
            MemoryDecisionKind.ACCEPT,
            MemoryDecisionKind.REINFORCE,
            MemoryDecisionKind.SUPERSEDE,
        }:
            return FindingUnwritten.REFUSED
        if kind is MemoryDecisionKind.REINFORCE:
            supports = create.memory.supports
            ledger.wrote(written, *(MemoryOperationKind.ADD_SUPPORT for _ in supports))
        else:
            ledger.wrote(written, MemoryOperationKind.CREATE)
        if retiring is not None:
            ledger.wrote(retiring.memory.id, retiring.kind)
        if kind is MemoryDecisionKind.SUPERSEDE:
            installed = await self._memory.get(written)
            if isinstance(installed, Memory):
                for retired in installed.operations[0].replaces:
                    ledger.wrote(retired, MemoryOperationKind.END)
        return None

    async def _asked(
        self, create: Create, result: MemoryIngestResult, ledger: _Ledger
    ) -> FindingUnwritten | None:
        """§13:1, §13:3: a ``policy_ask`` on each stored memory the ruling names, or none."""
        named = await self._memory.get_many(list(result.conflicts)) if result.conflicts else {}
        memories = [one for one in named.values() if isinstance(one, Memory)]
        if any(narrows(create.memory.placement, one) for one in memories):
            # §12:6: a question carries the supply onto the memory it is raised on, which
            # an operation cannot narrow (ADR-0328 §5:2): nothing is raised, and the
            # finding is retried rather than its ask dropped (§13:6).
            raise WriteBlocked
        if not memories or create.asked_on is None:
            return FindingUnwritten.ASKED
        for memory in memories:
            await self._raise(
                memory,
                OpenQuestionKind.POLICY_ASK,
                _ASK_ASKS + create.memory.content,
                create.asked_on,
                ledger,
            )
        return None

    async def _raise(
        self,
        target: Memory,
        kind: OpenQuestionKind,
        asks: str,
        support: MemorySupport,
        ledger: _Ledger,
    ) -> None:
        """Raise one open question on ``target``, resting on ``support`` (§13:1-§13:2)."""
        memory = await self._fresh(target)
        now = self._now()
        question = OpenQuestion(
            id=f"question:{self._mint()}",
            kind=kind,
            asks=asks,
            rests_on=(support.points_at,),
            raised_at=now,
            raised_by=MemoryWriterName.OBSERVER,
        )
        operation = MemoryOperation(
            kind=MemoryOperationKind.RAISE_QUESTION,
            cites=support.points_at,
            note=asks,
            at=now,
            by=MemoryWriterName.OBSERVER,
            question=question.id,
        )
        carried = memory.support_at(support.points_at)
        change = MemoryChange(
            memory=memory,
            operation=operation,
            support=None if carried is not None else support,
            question=question,
        )
        await self._guarded(
            self._writes.apply(change),
            {memory.id: (memory, lambda after: _applied(memory, after, operation))},
            lambda: ledger.wrote(memory.id, MemoryOperationKind.RAISE_QUESTION),
        )

    async def _resolve(self, resolve: Resolve, ledger: _Ledger) -> None:
        """§13:5: resolve the question, citing the support added from the answer."""
        memory = await self._fresh(resolve.target)
        held = next((one for one in memory.open_questions if one.id == resolve.question), None)
        if held is None or held.resolved:
            raise _Refusal(FindingUnwritten.CHECK_FAILED)
        operation = MemoryOperation(
            kind=MemoryOperationKind.RESOLVE_QUESTION,
            cites=resolve.support.points_at,
            note=resolve.note,
            at=self._now(),
            by=MemoryWriterName.OBSERVER,
            question=resolve.question,
        )
        carried = memory.support_at(resolve.support.points_at)
        change = MemoryChange(
            memory=memory,
            operation=operation,
            support=None if carried is not None else resolve.support,
        )
        await self._guarded(
            self._writes.apply(change),
            {memory.id: (memory, lambda after: _applied(memory, after, operation))},
            lambda: ledger.wrote(memory.id, MemoryOperationKind.RESOLVE_QUESTION),
        )

    async def _apply(
        self, memory: Memory, kind: MemoryOperationKind, support: MemorySupport, ledger: _Ledger
    ) -> None:
        """One add support citing ``support`` (§12:3), a no-op where it is carried (§4:8)."""
        operation = MemoryOperation(
            kind=kind,
            cites=support.points_at,
            note=support.note,
            at=self._now(),
            by=MemoryWriterName.OBSERVER,
        )
        carried = memory.support_at(support.points_at)
        change = MemoryChange(
            memory=memory, operation=operation, support=None if carried is not None else support
        )
        await self._guarded(
            self._writes.apply(change),
            {memory.id: (memory, lambda after: _applied(memory, after, operation))},
            lambda: ledger.wrote(memory.id, kind),
        )

    async def _fresh(self, memory: Memory) -> Memory:
        """``memory`` as the store holds it now, still at the revision decided on.

        The revision expected is the one this finding's own last write left the memory
        at, or else the one the commit step was shown (ADR-0219 §2).

        Raises:
            _Refusal: ``check_failed`` where the store no longer holds it as a memory.
            MemoryStoreStaleError: Where another writer moved it since: the finding is
                decided again on a retry (ADR-0219 §3).
        """
        held = await self._memory.get(memory.id)
        if not isinstance(held, Memory):
            raise _Refusal(FindingUnwritten.CHECK_FAILED)
        if held.revision != self._expected.get(memory.id, memory.revision):
            msg = "a memory moved between the read the observer decided on and its write"
            raise MemoryStoreStaleError(msg)
        return held

    async def _guarded[T](
        self,
        write: Awaitable[T],
        checks: Mapping[str, tuple[Memory, Callable[[Memory], bool]]],
        written: Callable[[], None] | None = None,
    ) -> T:
        """Await one write, note it in the ledger, then verify what it left.

        ``written`` notes the write in the finding's ledger as soon as it lands, before
        the verification, which may fail: what was written is recorded either way
        (§16:1).

        Raises:
            _Refusal: ``check_failed`` for a support whose episode the store does not
                hold (§9:5), ``refused`` for a self-consuming write or a fold onto a
                record the proposal cites (§12:5).
            MemoryStoreError: Every other failure or refusal, re-raised: the attempt is
                retried (§16:4); ``MemoryStoreStaleError`` where another writer's change
                is found beside this one's.
        """
        try:
            done = await write
        except UnresolvedEvidenceError as exc:
            raise _Refusal(FindingUnwritten.CHECK_FAILED) from exc
        except SelfConsumingWriteError as exc:
            raise _Refusal(FindingUnwritten.REFUSED) from exc
        if written is not None:
            written()
        await self._verified(checks)
        return done

    async def _verified(
        self, checks: Mapping[str, tuple[Memory, Callable[[Memory], bool]]]
    ) -> None:
        """Adopt a memory's new revision only where this finding's own write made it.

        Each memory is read again after the write: unchanged, it is left; changed exactly
        as this write changes it, its revision becomes the one the finding's next write
        expects; changed in any other way, another writer moved it in between, and the
        finding is decided again on a retry (ADR-0219 §2-§3).

        Raises:
            MemoryStoreStaleError: Where another writer's change is found.
        """
        if not checks:
            return
        found = await self._memory.get_many(list(checks))
        for memory_id, (before, mine) in checks.items():
            after = found.get(memory_id)
            if not isinstance(after, Memory) or after.revision == before.revision:
                continue
            if not mine(after):
                msg = "a memory moved beside the observer's own write"
                raise MemoryStoreStaleError(msg)
            self._expected[memory_id] = after.revision


def _extends(
    before: Memory, after: Memory, added: int, *, placement: Placement | None = None
) -> bool:
    """Whether ``after`` is ``before`` with ``added`` observer operations appended.

    The track record and the placement stay as they were (the placement becomes
    ``placement`` where a fold's meet is expected): a change to either is another
    writer's, since no operation writes them (ADR-0328 §5:2).
    """
    head = after.operations[: len(before.operations)]
    tail = after.operations[len(before.operations) :]
    return (
        head == before.operations
        and len(tail) == added
        and all(one.by is MemoryWriterName.OBSERVER for one in tail)
        and after.track_record == before.track_record
        and after.placement == (before.placement if placement is None else placement)
    )


def _applied(before: Memory, after: Memory, operation: MemoryOperation) -> bool:
    """One operation appended, and it is this one."""
    return _extends(before, after, 1) and after.operations[-1] == operation


def _retired(before: Memory, after: Memory, kind: MemoryOperationKind) -> bool:
    """One retiring operation of ``kind`` appended by the observer's proposal."""
    return _extends(before, after, 1) and after.operations[-1].kind is kind


def _reinforced(before: Memory, after: Memory, proposed: Memory) -> bool:
    """The proposal's supports added by one add support each, and the fold's meet alone.

    A ``REINFORCE`` adds each support the target did not carry by one add support, takes
    the placement's fold (ADR-0217 §3:3) and the union of topics (ADR-0213 §8), and
    changes nothing else (ADR-0328 §11:6, §11:9).
    """
    added = sum(1 for one in proposed.supports if before.support_at(one.points_at) is None)
    return (
        _extends(before, after, added, placement=before.placement.folded_with(proposed.placement))
        and all(after.support_at(one.points_at) is not None for one in proposed.supports)
        and set(after.topics) == set(before.topics) | set(proposed.topics)
    )


def _recorded(before: Memory, after: Memory, entry: TrackRecordEntry) -> bool:
    """The entry recorded, and nothing else changed (ADR-0328 §8:4)."""
    return (
        entry in after.track_record
        and len(after.track_record) == len(before.track_record) + 1
        and after.operations == before.operations
        and after.supports == before.supports
    )
