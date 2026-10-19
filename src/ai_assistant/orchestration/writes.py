"""The write stage: one route from a producer's proposal to the memory write path.

``MemoryWriter.ingest`` owns conflict resolution, the policy's ruling and the
write. This stage holds the writer by injection and adds nothing to the ruling:
it puts a proposal through, and reports what the writer ruled.

**An ``ASK_USER`` ruling writes nothing and is logged** (ADR-0309 §5). The
deferred-question queue ADR-0078 built for that ruling retired with the old path,
and the question surface that answered from it left the engine before it. So a
deferred proposal is parked nowhere: the writer has already written nothing on
that ruling, and this stage records one structured event carrying the ruling's
kind and the proposal's memory kind alone (ADR-0319 §5): no identifier and no
content of the proposal, since a memory id is not guaranteed free of personal
data (ADR-0004 §5). Whether a deferred proposal
should become something the user is asked is for the learning work to decide,
not this stage.

**One stage, injected into every producer's stage**, so every producer's proposal
takes the one route and is reported the same way. Its one producer, the
consolidation stage, retired (ADR-0328 §14:2), and nothing in production holds it
until another producer does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.types import MemoryDecisionKind

if TYPE_CHECKING:
    from ai_assistant.core.protocols import MemoryWriter
    from ai_assistant.core.types import MemoryIngestResult, MemoryUpdateProposal

_log = structlog.get_logger(__name__)

#: The event an ``ASK_USER`` ruling is logged under, carrying the ruling's kind and
#: the proposal's memory kind and nothing else of the proposal: no identifier and
#: no content (ADR-0319 §5, ADR-0004 §5).
DEFERRED_EVENT: Final = "memory_write_deferred"


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    """What the write stage did with one proposal.

    A frozen ``orchestration`` dataclass rather than a ``core`` model (ADR-0042 §1):
    it crosses no *subsystem* boundary.

    Attributes:
        result: The ruling and the id written, exactly as the ``MemoryWriter``
            returned it.
    """

    result: MemoryIngestResult


class MemoryWriteStage:
    """Puts one proposal through the write path, and logs what it defers.

    The stage every producer's stage writes through (module docstring). It rules on
    nothing and writes no memory itself: the injected ``MemoryWriter`` owns conflict
    resolution, the policy's ruling and the write.
    """

    def __init__(self, *, writer: MemoryWriter) -> None:
        """Wire the stage from the memory write path.

        ``writer`` must persist to the ``MemoryStore`` the producers read from.
        The type system cannot express that, so it is a composition-root obligation
        with a test behind it (ADR-0028 §4).

        Args:
            writer: The ratified memory write path: conflicts, the policy's ruling
                and persistence in one call. It holds the policy; this stage does
                not, and reads a ruling only to see whether it deferred.
        """
        self._writer = writer

    async def write(self, proposal: MemoryUpdateProposal) -> WriteOutcome:
        """Ingest ``proposal``, logging the ruling if the policy deferred it.

        An ``ASK_USER`` ruling writes nothing: the writer persists nothing on it,
        and this stage parks nothing. One :data:`DEFERRED_EVENT` is logged with the
        ruling's kind and the proposal's memory kind alone (ADR-0319 §5). It
        carries **no identifier and no content** of the proposal: not its id, which
        is not guaranteed free of personal data, nor its text, its rationale or the
        ruling's reason, any of which may carry the user's words (ADR-0004 §5).

        Args:
            proposal: The proposed memory update.

        Returns:
            The ruling, exactly as the writer returned it.

        Raises:
            MemoryStoreError: As the writer raises, including for a write-producing
                ruling on secret-tier data and an uncovered fold onto an assertion.
            UnresolvedEvidenceError: As the writer raises for a ``DERIVED``
                proposal citing a record the store does not hold.
        """
        # One observation of the caller's proposal, on this coroutine's first
        # executed line, before the ingest that is this method's first await
        # (ADR-0065). The memory kind logged below is read from this copy, so a
        # model tampered past `frozen=True` while the ingest is in flight cannot
        # change what the log names (ADR-0018 §3, ADR-0021 §4).
        observed = proposal.model_copy(deep=True)
        result = await self._writer.ingest(observed)
        if result.decision.kind is MemoryDecisionKind.ASK_USER:
            _log.info(
                DEFERRED_EVENT,
                ruling=result.decision.kind.value,
                memory_kind=observed.proposed.kind,
            )
        return WriteOutcome(result=result)
