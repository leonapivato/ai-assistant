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

        **Both branches carry ``about_person`` across, and the field it sits
        beside is not it** (ADR-0100 §7). ``event.subject`` is a preference
        *scope*: it lands as ``context`` on the preference branch and the semantic
        branch discards it, having nowhere to put a scope, exactly as ADR-0009 §1
        decided. The subject axis is not scoped that way — an asserted *fact* about
        someone else is as much about them as a preference is — so dropping it on
        the semantic branch would write ``None`` over a subject the user had just
        stated, and ADR-0100 §3 reads that ``None`` as *the owner's*. That is the
        false record §7 requires the input route in order to avoid, reintroduced
        one layer further down.
        """
        match event.memory_kind:
            case MemoryKind.PREFERENCE:
                return PreferenceMemory(
                    id=self._id_factory(),
                    content=event.content,
                    preference=event.content,
                    context=event.subject,
                    about_person=event.about_person,
                    provenance=self._provenance(event),
                )
            case MemoryKind.SEMANTIC:
                return SemanticMemory(
                    id=self._id_factory(),
                    content=event.content,
                    fact=event.content,
                    about_person=event.about_person,
                    provenance=self._provenance(event),
                )
            case _:  # PROCEDURAL, EPISODIC — need richer structure (deferred, ADR-0009 §6)
                return None

    @staticmethod
    def _provenance(event: FeedbackEvent) -> Provenance:
        """User-asserted provenance carrying the feedback's evidence and time.

        **The confirming instant is the utterance's, not the write's**
        (ADR-0109 §4). An ``ASSERTED`` belief is confirmed by the user stating it,
        so ``last_confirmed_at`` is ``event.created_at`` — the same discipline
        that keeps ``ATTESTED`` off our ingestion clock and ``DERIVED`` off the
        moment of derivation. Reading the ingest clock instead would make a
        re-processed feedback event look freshly confirmed.

        The two instants coincide here because this producer already takes its
        *transaction* stamp from the same event, which is the coincidence ADR-0103
        §9 warns "breaks silently". Whether that is the right transaction time is
        an ADR-0045 §3 question about a line ADR-0109 does not touch, filed as
        #775. What holds the two fields apart in the suite is the calendar reader,
        whose ``last_updated`` is ``read_at`` while its confirming instant is the
        source's ``reported_at``, and the fold, whose survivor takes the two from
        different sides (ADR-0109 §10).
        """
        return Provenance(
            source=MemorySource.USER_ASSERTED,
            confidence=_FULL_CONFIDENCE,
            evidence=event.evidence,
            last_updated=event.created_at,
            last_confirmed_at=event.created_at,
        )
