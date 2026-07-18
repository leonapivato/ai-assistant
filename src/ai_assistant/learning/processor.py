"""A first, deterministic :class:`~ai_assistant.core.protocols.FeedbackProcessor`.

``RuleBasedFeedbackProcessor`` maps *explicit, already-structured* feedback into
a :class:`~ai_assistant.core.types.MemoryUpdateProposal` (ADR-0009). It performs
no natural-language interpretation and no I/O: given the feedback's target
``memory_kind`` and ``content`` it builds the matching typed record with
``USER_ASSERTED`` provenance, so the existing :class:`DefaultMemoryPolicy`
accepts it and the loop "takes" on the first correction.

Interpreting freeform feedback is the job of a later model-backed processor
behind the same Protocol.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from ai_assistant.core.types import (
    MemoryKind,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    Provenance,
    SemanticMemory,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.types import FeedbackEvent, MemoryRecord

_FULL_CONFIDENCE = 1.0


def _uuid() -> str:
    return str(uuid.uuid4())


class RuleBasedFeedbackProcessor:
    """Maps explicit feedback to a user-asserted memory proposal.

    Structurally implements
    :class:`~ai_assistant.core.protocols.FeedbackProcessor`.
    """

    def __init__(self, *, id_factory: Callable[[], str] = _uuid) -> None:
        """Initialise the processor.

        Args:
            id_factory: Supplies ids for new records; injectable for
                deterministic tests. Defaults to random UUIDs.
        """
        self._id_factory = id_factory

    async def process(self, event: FeedbackEvent) -> Sequence[MemoryUpdateProposal]:
        """Return the proposal implied by ``event``, or nothing for a deferred kind."""
        record = self._to_record(event)
        if record is None:
            return []
        return [
            MemoryUpdateProposal(
                proposed=record,
                rationale=f"user {event.kind.value}: {event.content}",
            )
        ]

    def _to_record(self, event: FeedbackEvent) -> MemoryRecord | None:
        """Build the typed record for ``event``, or ``None`` for a deferred kind.

        A new id and provenance are minted only for a *supported* target, so a
        deferred kind does not consume an id from an allocating factory.
        """
        match event.memory_kind:
            case MemoryKind.PREFERENCE:
                return PreferenceMemory(
                    id=self._id_factory(),
                    content=event.content,
                    preference=event.content,
                    context=event.subject,
                    provenance=self._provenance(event),
                )
            case MemoryKind.SEMANTIC:
                return SemanticMemory(
                    id=self._id_factory(),
                    content=event.content,
                    fact=event.content,
                    provenance=self._provenance(event),
                )
            case _:  # PROCEDURAL, EPISODIC — need richer structure (deferred, ADR-0009 §6)
                return None

    @staticmethod
    def _provenance(event: FeedbackEvent) -> Provenance:
        """User-asserted provenance carrying the feedback's evidence and time."""
        return Provenance(
            source=MemorySource.USER_ASSERTED,
            confidence=_FULL_CONFIDENCE,
            evidence=list(event.evidence),
            last_updated=event.created_at,
        )
