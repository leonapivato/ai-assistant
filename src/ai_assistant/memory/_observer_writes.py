"""The write path's rules for what the observer writes (ADR-0329 §9:7, §12:4, §12:5).

Two admission rules the writer holds whatever producer hands it a proposal:

- **An observer's inference** (§9:7) is ``for`` and backs the claim as worded only on a
  memory whose other supports added with it are all ``for`` and none backs the claim as
  worded, and is ``against`` only on a memory the ingest creating its memory retires;
  its ``when`` is the ``occurred_at`` of the episode whose processing drew it.
- **A retiring operation** a proposal carries (§12:4) cites a counted ``for`` support of
  the new memory backing it as worded (§12:5), a confirmation only where ADR-0328 §4:6
  lets that ingest retire the memory, and is applied to the retired memory as any
  operation is, so ADR-0328 §6:5 refuses a cited support ranking below its standing.

Pure functions of their arguments, in ``memory`` beside the operation transition
(:mod:`ai_assistant.memory._operations`) for the reason that one is here: the rules are
the writer's, and ``core`` keeps only the shapes (ADR-0016 §2). The canonical fake
(:mod:`ai_assistant.testing.writer`) carries its own copy, since no testing module
imports ``memory``; the shared writer contract suite holds both to the same refusals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    BeliefBand,
    EpisodicMemory,
    Memory,
    MemoryOperation,
    MemorySupport,
    MemoryWriterName,
    SupportDirection,
    SupportOrigin,
    part_episode,
    record_band,
)
from ai_assistant.memory._operations import applied_operation

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from ai_assistant.core.types import MemoryRecord, MemoryRetirement, MemoryUpdateProposal

__all__ = [
    "added_inference_fault",
    "inference_fault",
    "inference_when_fault",
    "replaces_with",
    "retired_memory",
    "retirement_fault",
]

#: The bands a confirmation may retire without the question having shown it replaced:
#: ADR-0079 §3's retirement class, widened by ADR-0092 §4, read through ADR-0328 §12.
_RETIREMENT_CLASS: Final = frozenset({BeliefBand.DERIVED, BeliefBand.ATTESTED})


def inference_fault(supports: Sequence[MemorySupport]) -> str | None:
    """Which of §9:7's rules the supports one write adds with a new memory break, if any.

    ``supports`` are the supports added together with a memory being created: a
    proposal's memory, or the successor an operation creates. Among them an inference
    is at most one, ``for`` and backing the claim as worded, beside at least one other
    support, every other one ``for`` and none backing the claim as worded — the claim
    is the inference's own reading of them. An ``against`` inference belongs on a
    memory the ingest creating its memory retires, which the writer adds itself, and
    never on a memory a producer hands it.

    Args:
        supports: The supports one write adds with a new memory.

    Returns:
        The rule broken, or ``None``.
    """
    inferences = [one for one in supports if one.origin is SupportOrigin.OBSERVER_INFERENCE]
    if not inferences:
        return None
    others = [one for one in supports if one.origin is not SupportOrigin.OBSERVER_INFERENCE]
    clauses: tuple[tuple[bool, str], ...] = (
        (
            any(one.direction is SupportDirection.AGAINST for one in inferences),
            "an observer's inference is against only a memory the ingest creating its "
            "memory retires",
        ),
        (
            len(inferences) > 1 or not inferences[0].backs_as_worded,
            "an observer's inference is one support, for and backing the claim as worded",
        ),
        (
            not others
            or any(
                one.direction is not SupportDirection.FOR or one.backs_as_worded for one in others
            ),
            "an observer's inference backs only a claim that is its reading of the other "
            "supports added with it, each for and none backing the claim as worded",
        ),
    )
    fault = next((fault for broken, fault in clauses if broken), None)
    return None if fault is None else f"{fault} (ADR-0329 §9:7)"


def added_inference_fault(support: MemorySupport | None) -> str | None:
    """§9:7's refusal of an inference that one operation would add on its own.

    An operation adds one support (ADR-0328 §5's table), so an inference it added would
    be added with no other support: never the reading of others ``for`` it, and never
    ``against`` a memory an ingest retires.

    Args:
        support: The support an operation adds, where the memory does not carry it yet.

    Returns:
        The rule broken, or ``None``.
    """
    if support is None or support.origin is not SupportOrigin.OBSERVER_INFERENCE:
        return None
    return (
        "an observer's inference is added only with a memory an ingest creates, beside "
        "the supports it reads, or against a memory that ingest retires (ADR-0329 §9:7)"
    )


def inference_when_fault(
    supports: Sequence[MemorySupport], held: Mapping[str, MemoryRecord]
) -> str | None:
    """§9:7: an inference's ``when`` is its episode's ``occurred_at``.

    Args:
        supports: The supports a write adds.
        held: The episodes the store holds, by id, read for those supports (§4:7).

    Returns:
        The rule broken, or ``None``.
    """
    for support in supports:
        if support.origin is not SupportOrigin.OBSERVER_INFERENCE:
            continue
        address = part_episode(support.points_at)
        episode = None if address is None else held.get(address)
        if not isinstance(episode, EpisodicMemory) or support.when != episode.occurred_at:
            return (
                "an observer's inference is dated at the occurred_at of the episode whose "
                "processing drew it (ADR-0329 §9:7)"
            )
    return None


def _confirmation_covers(memory: Memory, proposal: MemoryUpdateProposal) -> bool:
    """Whether the proposal's confirmation authorises retiring ``memory`` (ADR-0078 §5b).

    ADR-0078 §5b's checks that a retirement can make: the memory is among those the
    answer authorises retiring, the confirmation is bound to this very question — its
    key recomputed from the proposal as handed — and every id it authorises was among
    the conflicts the question froze.
    """
    confirmation = proposal.confirmation
    return (
        confirmation is not None
        and memory.id in confirmation.retires
        and confirmation.question_key == proposal.question_key
        and set(proposal.conflicts).issuperset(confirmation.retires)
    )


def retirement_fault(proposal: MemoryUpdateProposal) -> str | None:
    """Which of §12:4's and §12:5's rules the proposal's retiring operation breaks.

    The cited support is a counted ``for`` support of the new memory that backs it as
    worded (§12:5). The retired memory does not carry the part it points at already, so
    the support the operation cites on it is the one the writer adds (§12:4, as
    ADR-0328 §11:7 refuses for a supersession). A confirmation is cited only where
    ADR-0328 §4:6 lets this ingest retire the memory: a ``DERIVED`` or ``ATTESTED`` one
    (ADR-0079 §3), and an ``ASSERTED`` one only where the question showed it replaced
    (ADR-0078 §5, ADR-0321 §5:5), which the proposal's confirmation records.

    Args:
        proposal: The proposal, as handed to the writer.

    Returns:
        The rule broken, or ``None`` where it carries no retiring operation.
    """
    retiring = proposal.retiring
    if retiring is None:
        return None
    cited = next(
        (one for one in proposal.proposed.backing_supports if one.points_at == retiring.cites),
        None,
    )
    if cited is None:
        return (
            "a retiring operation cites a counted for support of the new memory that backs "
            "it as worded (ADR-0329 §12:5)"
        )
    if retiring.memory.support_at(retiring.cites) is not None:
        return (
            "a retiring operation adds the support it cites to the retired memory, which "
            "carries that part already (ADR-0329 §12:4)"
        )
    if (
        cited.origin is SupportOrigin.CONFIRMATION
        and record_band(retiring.memory) not in _RETIREMENT_CLASS
        and not _confirmation_covers(retiring.memory, proposal)
    ):
        return (
            "a confirmation retires a memory the user asserted only where the question "
            "showed it replaced (ADR-0328 §4:6, ADR-0329 §12:4)"
        )
    return None


def retired_memory(
    retiring: MemoryRetirement,
    cited: MemorySupport,
    *,
    successor: str | None,
    at: datetime,
    by: MemoryWriterName,
) -> Memory:
    """The retired memory once the retiring operation is applied (§12:4).

    The cited support is added to it as an ``against`` support that does not back it as
    worded, and the operation cites it, naming ``successor`` or none. Applied by the
    operation transition, so every rule ADR-0328 §5 and §6:5 hold refuses it there.

    Args:
        retiring: The retirement the proposal carries.
        cited: The new memory's support it cites.
        successor: The new memory's id on an ``ACCEPT``, ``None`` on a ``REINFORCE``.
        at: The operation's instant.
        by: The writer that wrote the new memory's create.

    Returns:
        The retired memory as the write leaves it.

    Raises:
        ValueError: If any rule of §4, §5 or §6:5 refuses the operation.
    """
    against = MemorySupport.model_validate(
        cited.model_dump()
        | {"direction": SupportDirection.AGAINST, "backs_as_worded": False, "added_at": at}
    )
    operation = MemoryOperation(
        kind=retiring.kind,
        cites=retiring.cites,
        note=retiring.note,
        at=at,
        by=by,
        successor=successor,
    )
    return applied_operation(retiring.memory, operation, support=against)


def replaces_with(memory: Memory, retired: str) -> Memory:
    """``memory`` with its create naming ``retired`` among those it replaces (§5:6).

    Args:
        memory: The new memory.
        retired: The id of the memory it retires.

    Returns:
        The memory its install writes.
    """
    first, *rest = memory.operations
    create = first.model_copy(update={"replaces": tuple(dict.fromkeys([*first.replaces, retired]))})
    return memory.model_copy(update={"operations": (create, *rest)})
