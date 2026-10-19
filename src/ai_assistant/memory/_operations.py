"""One operation applied to one stored memory: the record it yields (ADR-0328 §5, §11:3).

The writer's member "computing the record it yields" (§11:3), so it lives here, in the
subsystem that owns the memory's transitions, and not on the type in ``core``: a state
transition stays subsystem code even when it is pure (ADR-0016 §2 keeps ADR-0014's
"deterministic subsystem code owns state transitions" untouched). What ``core`` keeps is
the operation's shape and the record's structural validators, and §7's computed values.

The canonical fake (:mod:`ai_assistant.testing.writer`) carries its own implementation,
since no testing module imports ``memory``; the shared writer contract suite holds both
to the same records and the same refusals.
"""

from __future__ import annotations

from typing import Final

from ai_assistant.core.types import (
    RETIRING_OPERATIONS,
    Memory,
    MemoryOperation,
    MemoryOperationKind,
    MemoryStatus,
    MemorySupport,
    OpenQuestion,
    Validity,
    origin_standing,
    standing_rank,
)

__all__ = ["applied_operation"]


def _refuse_lower_standing(
    memory: Memory, operation: MemoryOperation, cited: MemorySupport
) -> None:
    """ADR-0328 §6:5: a lower standing never silently overrides a higher one.

    Raises:
        ValueError: If ``operation`` retires the memory on a support whose origin ranks
            below the memory's standing, or stops a support on one whose origin ranks
            below the stopped support's.
    """
    rank = standing_rank(origin_standing(cited.origin))
    if operation.kind in RETIRING_OPERATIONS and rank < standing_rank(memory.standing):
        msg = (
            f"a {operation.kind} citing a {cited.origin} support ranks below the memory's "
            f"standing, {memory.standing}; the open question it needs is raised instead "
            f"(ADR-0328 §6:5)"
        )
        raise ValueError(msg)
    stopped = None if operation.stops is None else memory.support_at(operation.stops)
    if stopped is not None and rank < standing_rank(origin_standing(stopped.origin)):
        msg = (
            f"a stop counting citing a {cited.origin} support ranks below the {stopped.origin} "
            f"support it would stop (ADR-0328 §6:5)"
        )
        raise ValueError(msg)


def _closed_window(memory: Memory, operation: MemoryOperation, cited: MemorySupport) -> Validity:
    """The window a retiring operation leaves (ADR-0328 §5:10, §5:11).

    An end closes at its cited support's about-when where it carries one, and at the
    operation's instant otherwise; a mark wrong and a replace close at the operation's
    instant. The close clamps and never resurrects (ADR-0080 §1).

    Raises:
        ValueError: If an end's about-when lies after its instant, or no
            representable close exists (ADR-0080 §3).
    """
    close = operation.at
    if operation.kind is MemoryOperationKind.END and cited.about_when is not None:
        if cited.about_when > operation.at:
            msg = (
                "an end whose about-when lies after its instant is refused: a claim that "
                "holds until a later time is worded so (ADR-0328 §5:10)"
            )
            raise ValueError(msg)
        close = cited.about_when
    window = memory.validity
    end = close if window.valid_until is None else min(close, window.valid_until)
    if window.valid_from is not None and end <= window.valid_from:
        msg = (
            f"cannot close {memory.id!r} at {end.isoformat()}, at or before its valid_from "
            f"{window.valid_from.isoformat()} (ADR-0328 §5:11, ADR-0080 §3)"
        )
        raise ValueError(msg)
    return window.model_copy(update={"valid_until": end})


def _resolved_questions(
    memory: Memory, operation: MemoryOperation, question: OpenQuestion | None
) -> tuple[OpenQuestion, ...]:
    """The open questions after a raise or a resolve (ADR-0328 §9:2).

    Raises:
        ValueError: If a raise carries no question or a different one, or a resolve
            names a question the memory does not carry open.
    """
    if operation.kind is MemoryOperationKind.RAISE_QUESTION:
        if question is None or question.id != operation.question or question.resolved:
            msg = "a raise question carries the open question it raises (ADR-0328 §9:2)"
            raise ValueError(msg)
        if operation.cites not in question.rests_on:
            msg = "a raise question cites a support the question rests on (ADR-0328 §5)"
            raise ValueError(msg)
        return (*memory.open_questions, question)
    if operation.kind is not MemoryOperationKind.RESOLVE_QUESTION:
        return memory.open_questions
    named = [one for one in memory.open_questions if one.id == operation.question]
    if not named or named[0].resolved:
        msg = "a resolve question names a question the memory carries open (ADR-0328 §9:2)"
        raise ValueError(msg)
    resolved = named[0].model_copy(
        update={
            "resolved_at": operation.at,
            "resolved_by": operation.cites,
            "resolution": operation.note,
        }
    )
    return tuple(resolved if one.id == resolved.id else one for one in memory.open_questions)


_STATUS_AFTER: Final[dict[MemoryOperationKind, MemoryStatus]] = {
    MemoryOperationKind.END: MemoryStatus.ENDED,
    MemoryOperationKind.REPLACE: MemoryStatus.ENDED,
    MemoryOperationKind.MARK_WRONG: MemoryStatus.WRONG,
}


def applied_operation(
    memory: Memory,
    operation: MemoryOperation,
    *,
    support: MemorySupport | None = None,
    question: OpenQuestion | None = None,
) -> Memory:
    """The memory one operation yields (ADR-0328 §5), or the refusal §4, §5 or §6:5 makes.

    A pure function of its arguments. It reads no store: whether a support's episode is
    held (§4:7) and whether the stored revision is the one read (§5:4) are
    :class:`~ai_assistant.memory.ingest.MemoryIngestor`'s to check.

    - ``support``, where given, is the support the operation cites, added in the same
      write (§5:3). One whose part the memory already carries is not added, and the one
      already there keeps its fields (§4:8); an add support citing it then changes
      nothing, and the memory is returned unchanged.
    - A retiring operation closes the validity as §5:10 and §5:11 say and sets the
      status §5:7 gives; a stop counting stops the support it names (§5:8); a raise
      question adds ``question``, and a resolve question records its resolution (§9:2).
    - Nothing is removed: no support, operation, entry or question (§5:5).

    Args:
        memory: The memory as read.
        operation: The operation.
        support: The support it cites, where the memory does not carry it yet.
        question: The question a raise question raises.

    Returns:
        The memory it yields, validated whole, its revision the one read.

    Raises:
        ValueError: If the operation is a create, its support is not the one it cites,
            it cites a support the memory does not carry once applied, or any rule of
            §4, §5, §6:5 or §9 refuses it.
    """
    if operation.kind is MemoryOperationKind.CREATE:
        msg = "a create starts a memory and is never applied to one (ADR-0328 §11:4)"
        raise ValueError(msg)
    if support is not None and support.points_at != operation.cites:
        msg = "the support an operation adds is the one it cites (ADR-0328 §5:3)"
        raise ValueError(msg)
    carried = memory.support_at(operation.cites)
    if carried is not None and operation.kind is MemoryOperationKind.ADD_SUPPORT:
        return memory
    cited = carried if carried is not None else support
    if cited is None:
        msg = "an operation cites a support the memory carries once it is applied (§5:3)"
        raise ValueError(msg)
    _refuse_lower_standing(memory, operation, cited)
    supports = memory.supports if carried is not None else (*memory.supports, cited)
    update: dict[str, object] = {
        "supports": supports,
        "operations": (*memory.operations, operation),
        "open_questions": _resolved_questions(memory, operation, question),
    }
    if operation.kind in RETIRING_OPERATIONS:
        update["validity"] = _closed_window(memory, operation, cited)
        update["status"] = _STATUS_AFTER[operation.kind]
    dumped = memory.model_dump()
    dumped.update(update)
    return Memory.model_validate(dumped)
