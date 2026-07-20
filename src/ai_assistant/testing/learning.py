"""A canonical :class:`~ai_assistant.core.protocols.FeedbackProcessor` fake.

The shared test double for the ``FeedbackProcessor`` contract, so a subsystem
that consumes the learning step (``orchestration``, ...) can drive feedback to
any outcome it needs to exercise *without importing the learning subsystem's
internals* (CLAUDE.md golden rule 1) and without depending on
``RuleBasedFeedbackProcessor``'s particular rules — which are an implementation
choice and expected to change once a model-backed processor lands (ADR-0009 §6).

That independence is what makes it useful. The rule-based processor *defers*
procedural and episodic targets, so a consumer that wanted "the processor
proposed an episodic memory" could not express it against the real
implementation at all. The fake synthesises a well-formed proposal for every
:class:`~ai_assistant.core.types.MemoryKind`, and a test that wants an exact
proposal — or none — scripts one instead.

Beyond the contract it records every event it was given to :attr:`events`, so a
test can assert what its subject actually fed the learning step. Only the
behaviour pinned by the shared ``FeedbackProcessor`` conformance suite is part of
the contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.core.types import (
    EpisodicMemory,
    FeedbackEvent,
    MemoryKind,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    ProceduralMemory,
    Provenance,
    SemanticMemory,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.types import MemoryRecord

_FULL_CONFIDENCE = 1.0


def _sequential_ids() -> Callable[[], str]:
    """Return a per-instance id factory yielding ``fake-memory-1``, ``-2``, ..."""
    issued = 0

    def factory() -> str:
        nonlocal issued
        issued += 1
        return f"fake-memory-{issued}"

    return factory


class FakeFeedbackProcessor:
    """A ``FeedbackProcessor`` test double returning scripted or synthesised proposals.

    Structurally implements
    :class:`~ai_assistant.core.protocols.FeedbackProcessor`. Every call is
    appended to :attr:`events` and answered with the scripted proposals, or — by
    default — with one proposal synthesised from the event itself.
    """

    def __init__(
        self,
        proposals: Sequence[MemoryUpdateProposal] | None = None,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Create the fake processor.

        Args:
            proposals: Returned verbatim for every event. ``None`` (the default)
                synthesises one proposal per event instead; an *empty* sequence
                is the distinct, explicit "this processor proposes nothing", which
                a consumer needs to exercise its no-op learning path.
            id_factory: Supplies ids for synthesised records; injectable for
                deterministic tests. Defaults to a per-instance counter, so two
                fakes never hand out ids that collide in a shared store.

        Raises:
            ValueError: If any scripted proposal has blank ``proposed.content`` or
                a blank ``rationale``. Neither is rejected by
                :class:`~ai_assistant.core.types.MemoryUpdateProposal` itself, but
                both are pinned by the ``FeedbackProcessor`` conformance suite —
                so a fake configured this way could only surface as a contract
                violation at ``process`` time, far from the mistake. The canonical
                fake must not be configurable into breaking its own contract.
        """
        if proposals is not None:
            for index, proposal in enumerate(proposals):
                if not proposal.proposed.content.strip():
                    msg = f"proposals[{index}]: proposed.content must not be blank"
                    raise ValueError(msg)
                if not proposal.rationale.strip():
                    msg = f"proposals[{index}]: rationale must not be blank"
                    raise ValueError(msg)
        # Snapshotted on ingress as well as egress: the script is fixed *at
        # construction*, so a caller keeping its reference and mutating a proposal
        # later must not be able to change what `process` returns.
        self._proposals: tuple[MemoryUpdateProposal, ...] | None = (
            None if proposals is None else tuple(p.model_copy(deep=True) for p in proposals)
        )
        self._id_factory = id_factory if id_factory is not None else _sequential_ids()
        self.events: list[FeedbackEvent] = []

    async def process(self, event: FeedbackEvent) -> Sequence[MemoryUpdateProposal]:
        """Record the event and return the scripted or synthesised proposals.

        The returned proposals are deep copies, so a caller that mutates one
        cannot reach the fake's script and change what a later call sees.
        """
        self.events.append(event.model_copy(deep=True))
        if self._proposals is not None:
            return [p.model_copy(deep=True) for p in self._proposals]
        return [
            MemoryUpdateProposal(
                proposed=self._to_record(event),
                rationale=f"fake: user {event.kind.value}: {event.content}",
            )
        ]

    def _to_record(self, event: FeedbackEvent) -> MemoryRecord:
        """Build the typed record ``event`` targets.

        Unlike ``RuleBasedFeedbackProcessor`` every kind is covered, so a consumer
        can exercise the branch it cares about rather than the two the production
        rules happen to support today.
        """
        record_id = self._id_factory()
        provenance = self._provenance(event)
        match event.memory_kind:
            case MemoryKind.PREFERENCE:
                return PreferenceMemory(
                    id=record_id,
                    content=event.content,
                    provenance=provenance,
                    preference=event.content,
                    context=event.subject,
                )
            case MemoryKind.SEMANTIC:
                return SemanticMemory(
                    id=record_id,
                    content=event.content,
                    provenance=provenance,
                    fact=event.content,
                )
            case MemoryKind.PROCEDURAL:
                return ProceduralMemory(
                    id=record_id,
                    content=event.content,
                    provenance=provenance,
                    situation=event.subject if event.subject else event.content,
                    steps=[event.content],
                )
            case MemoryKind.EPISODIC:
                return EpisodicMemory(
                    id=record_id,
                    content=event.content,
                    provenance=provenance,
                    occurred_at=event.created_at,
                )

    @staticmethod
    def _provenance(event: FeedbackEvent) -> Provenance:
        """User-asserted provenance carrying the feedback's evidence and time."""
        return Provenance(
            source=MemorySource.USER_ASSERTED,
            confidence=_FULL_CONFIDENCE,
            evidence=list(event.evidence),
            last_updated=event.created_at,
        )

    @property
    def call_count(self) -> int:
        """How many times ``process`` has been called."""
        return len(self.events)

    @property
    def last_event(self) -> FeedbackEvent:
        """The recorded snapshot of the most recent call's event.

        Equal to what the caller passed, but not the same object — compare it by
        value, not identity.

        Raises:
            IndexError: If ``process`` has not been called.
        """
        return self.events[-1]
