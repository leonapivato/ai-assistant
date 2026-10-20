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

Each memory written on is read again just before its write, so the write is conditional
on the revision it now stands at (ADR-0219 §2). Every write adds to the record and none
removes anything (§12:7): a support already on a memory changes nothing (ADR-0328 §4:8),
and it is recorded as its add support, so a finding processed again after a clear says
what the memory carries rather than nothing.

**The outcome** names what was written, with the memory ids and the operations, or why
nothing was (§16:1). A ruling that writes nothing is ``refused``; an ``ASK_USER`` ruling
raises a ``policy_ask`` question on each stored memory it names (§13:1), and one that
names none writes nothing and is ``asked`` (§13:3) — never logged and dropped (§13:6).
A write the writer refuses is ``refused`` (§12:5), and one whose part points at an
episode the store no longer holds failed §9:5's check. A stale read and a store whose
deadline passed are not outcomes: they fail the attempt, which is retried (§16:4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import (
    MemoryStoreEmbeddingExpiredError,
    MemoryStoreError,
    MemoryStoreStaleError,
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
    Checked,
    Create,
    RaiseQuestion,
    RecordUse,
    Resolve,
    Unwritten,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime

    from ai_assistant.core.protocols import MemoryStore
    from ai_assistant.core.types import MemoryIngestResult, MemorySupport
    from ai_assistant.orchestration.writes import MemoryWriteStage

__all__ = ["FindingWriter"]

#: What a ``policy_ask`` question asks, in words, before the claim the policy asked about.
_ASK_ASKS: Final = "The write path asked before keeping this beside this memory: "


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

    async def write(self, checked: Checked) -> FindingOutcome:
        """Write ``checked`` and return the finding's outcome (§16:1).

        Args:
            checked: The decision, after code's checks.

        Returns:
            What was written, or why nothing was.

        Raises:
            MemoryStoreStaleError: Where a memory moved between its read and its write,
                so the attempt is retried (§16:4).
            MemoryStoreEmbeddingExpiredError: Where the store's deadline passed.
        """
        ledger = _Ledger()
        unwritten: FindingUnwritten | None = None
        try:
            unwritten = await self._primary(checked.primary, ledger)
        except _Refusal as refusal:
            unwritten = refusal.reason
        if checked.resolve is not None:
            try:
                await self._resolve(checked.resolve, ledger)
            except _Refusal as refusal:
                unwritten = unwritten or refusal.reason
        return ledger.outcome(self._now(), unwritten)

    async def _primary(
        self,
        primary: Create | AddSupports | RaiseQuestion | RecordUse | Unwritten,
        ledger: _Ledger,
    ) -> FindingUnwritten | None:
        match primary:
            case Unwritten(reason=reason):
                return reason
            case Create():
                return await self._create(primary, ledger)
            case AddSupports():
                target = await self._fresh(primary.target)
                for support in primary.supports:
                    await self._apply(target, MemoryOperationKind.ADD_SUPPORT, support)
                    target = await self._fresh(target)
                ledger.wrote(
                    target.id, *(MemoryOperationKind.ADD_SUPPORT for _ in primary.supports)
                )
                return None
            case RaiseQuestion():
                await self._raise(primary.target, primary.kind, primary.asks, primary.support)
                ledger.wrote(primary.target.id, MemoryOperationKind.RAISE_QUESTION)
                return None
            case RecordUse():
                memory = await self._fresh(primary.memory)
                await self._guarded(self._writes.record_use(memory, primary.entry))
                ledger.recorded(memory.id, held_up=primary.entry.held_up)
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
        outcome = await self._guarded(self._writes.write(proposal))
        result = outcome.result
        ledger.ruling = result.decision.kind
        return await self._ruled(create, retiring, result, ledger)

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
        if not memories or create.asked_on is None:
            return FindingUnwritten.ASKED
        for memory in memories:
            await self._raise(
                memory,
                OpenQuestionKind.POLICY_ASK,
                _ASK_ASKS + create.memory.content,
                create.asked_on,
            )
            ledger.wrote(memory.id, MemoryOperationKind.RAISE_QUESTION)
        return None

    async def _raise(
        self, target: Memory, kind: OpenQuestionKind, asks: str, support: MemorySupport
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
        await self._guarded(self._writes.apply(change))

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
        await self._guarded(self._writes.apply(change))
        ledger.wrote(memory.id, MemoryOperationKind.RESOLVE_QUESTION)

    async def _apply(
        self, memory: Memory, kind: MemoryOperationKind, support: MemorySupport
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
        await self._guarded(self._writes.apply(change))

    async def _fresh(self, memory: Memory) -> Memory:
        """``memory`` as the store holds it now, so a write is conditional on that revision.

        Raises:
            _Refusal: ``check_failed`` where the store no longer holds it as a memory.
        """
        held = await self._memory.get(memory.id)
        if not isinstance(held, Memory):
            raise _Refusal(FindingUnwritten.CHECK_FAILED)
        return held

    async def _guarded[T](self, write: Awaitable[T]) -> T:
        """Await one write, turning the writer's refusals into the outcome they are.

        Raises:
            _Refusal: ``check_failed`` for a support whose episode the store does not
                hold (§9:5), ``refused`` for any other refusal (§12:5).
            MemoryStoreStaleError: Re-raised: the attempt is retried (§16:4).
            MemoryStoreEmbeddingExpiredError: Re-raised, likewise.
        """
        try:
            return await write
        except MemoryStoreStaleError, MemoryStoreEmbeddingExpiredError:
            raise
        except UnresolvedEvidenceError as exc:
            raise _Refusal(FindingUnwritten.CHECK_FAILED) from exc
        except MemoryStoreError as exc:
            raise _Refusal(FindingUnwritten.REFUSED) from exc
