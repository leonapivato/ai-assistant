"""A first, deterministic :class:`~ai_assistant.core.protocols.FeedbackProcessor`.

``RuleBasedFeedbackProcessor`` maps *explicit, already-structured* feedback into
a :class:`~ai_assistant.core.types.MemoryUpdateProposal` (ADR-0009). It performs
no natural-language interpretation and no I/O: given the feedback's *resolved*
target ``memory_kind`` and its ``content`` it builds the matching typed record
with ``USER_ASSERTED`` provenance, so the existing :class:`DefaultMemoryPolicy`
accepts it and the loop "takes" on the first correction.

Resolving an absent ``memory_kind`` is not its job and it does not do it
(ADR-0122 §3): the pipeline holds the store, the processor holds nothing, and a
processor that read its own target would need a store seam injected into every
implementation behind this Protocol to answer a question that is the same for
all of them — while `learning` stays dependent only on `core` (ADR-0009 §3). So
an unresolved event is *refused* here rather than answered (§7).

Its one seam beyond the model of the feedback itself is an injected clock, which
stamps *transaction* time on what it proposes (ADR-0045 §3). The event supplies
the instants that are facts about the world; the clock supplies the one that is a
fact about our write.

Interpreting freeform feedback is the job of a later model-backed processor
behind the same Protocol.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ai_assistant.core.clock import checked_clock
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

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import FeedbackEvent, MemoryRecord

_FULL_CONFIDENCE = 1.0


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RuleBasedFeedbackProcessor:
    """Maps explicit feedback to a user-asserted memory proposal.

    Structurally implements
    :class:`~ai_assistant.core.protocols.FeedbackProcessor`.
    """

    def __init__(self, *, now: Clock = _utcnow, id_factory: Callable[[], str] = _uuid) -> None:
        """Initialise the processor.

        Args:
            now: Clock for each proposed record's ``provenance.last_updated`` —
                *transaction* time, and so ours rather than the event's
                (ADR-0045 §3). Injectable for deterministic tests, and guarded by
                :func:`~ai_assistant.core.clock.checked_clock` (ADR-0026 §7).
            id_factory: Supplies ids for new records; injectable for
                deterministic tests. Defaults to random UUIDs.
        """
        self._clock = checked_clock(now, owner="RuleBasedFeedbackProcessor")
        self._id_factory = id_factory

    async def process(self, event: FeedbackEvent) -> Sequence[MemoryUpdateProposal]:
        """Return the proposal implied by ``event``, or nothing for a deferred kind.

        Args:
            event: The explicit, already-structured feedback to interpret.

        Returns:
            One proposal for a supported target, and an empty sequence for a
            deferred one.

        Raises:
            ValueError: If ``event.memory_kind`` is ``None`` — a producer that
                skipped the pipeline stage owing the resolution (ADR-0122 §7); see
                :meth:`_to_record` for why that is a raise rather than the deferred
                target's silence. Or if the injected clock's reading does not
                conform — a :class:`~ai_assistant.core.clock.ClockReadingError`,
                which is a ``ValueError`` and is left unwrapped: `learning` has no
                error class of its own to translate either into, and the distinct
                subclass keeps a refused *reading* separable from a failure of the
                clock itself (ADR-0026 §2, §4). A deferred target reads no clock, so
                it cannot raise the second; an unresolved event raises the first
                before any clock is read at all.
        """
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
        deferred kind consumes neither an id from an allocating factory nor a
        reading from a clock that advances on being read.

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

        **An unresolved ``memory_kind`` is refused, not deferred** (ADR-0122 §7).
        The final arm's ``None`` is the right answer for a ``PROCEDURAL`` or
        ``EPISODIC`` target ADR-0009 §6 defers: there is nothing this processor can
        build yet, and ``process`` reporting no proposal says so. ``None`` on the
        *field* is a different thing — a producer that skipped the stage owing the
        resolution — and answering it with the deferred arm's silence would report
        "nothing to propose" for feedback that had everything to propose. That is
        the silent drop ADR-0122 exists to remove, reintroduced one layer down, and
        it would be invisible: ``learn`` would write nothing and report nothing
        wrong. Failing loudly is the discipline the neighbouring write path already
        takes, where ``_apply`` raises rather than storing a proposal whose fold
        names an absent target — "a write that loses data while reporting success is
        worse than one that stops".

        Raises:
            ValueError: If ``event.memory_kind`` is ``None``.
        """
        match event.memory_kind:
            case None:
                msg = (
                    "a FeedbackEvent reaching a FeedbackProcessor must carry a resolved "
                    "memory_kind; the calling stage resolves an absent one before this "
                    "call (ADR-0122 §3, §7)"
                )
                raise ValueError(msg)
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

    def _provenance(self, event: FeedbackEvent) -> Provenance:
        """User-asserted provenance carrying the feedback's evidence and two instants.

        **The two instants come from different clocks, and each answers to its
        own rule.** They are not two spellings of one quantity, and the fact that
        a live path puts them microseconds apart is the coincidence ADR-0103 §9
        warns "breaks silently" — so each is taken from its own source here.

        ``last_confirmed_at`` **is the utterance's instant, not the write's**
        (ADR-0109 §4): an ``ASSERTED`` belief is confirmed by the user stating it,
        so it is ``event.created_at``. That is the same discipline which keeps
        ``ATTESTED`` off our ingestion clock and ``DERIVED`` off the moment of
        derivation, and reading a clock for it instead would make a re-processed
        feedback event look freshly confirmed. The instant is written as it stands,
        including one ahead of our own clock, because the usability test belongs to
        the fold alone (ADR-0109 §4's fourth clause, ADR-0092 §3).

        ``last_updated`` **is transaction time, and so it is our clock at this
        write** (ADR-0045 §3): "when *we* last revised the belief" — the clock of
        the store changing its mind, never the clock of when the belief holds.
        ``event.created_at`` is a fact about the world rather than about our write,
        and taking the stamp from it made the record claim a revision at an instant
        nothing was revised at, wrongly by exactly the delay of a queued, retried or
        replayed event (#775).

        The clock is read **here**, on the branches that mint a record, rather than
        once in ``process``: a deferred target has nothing to stamp, and reading for
        it would consume a reading and turn a misconfigured clock into a failure of
        a call that today returns nothing and touches no seam.
        """
        return Provenance(
            source=MemorySource.USER_ASSERTED,
            confidence=_FULL_CONFIDENCE,
            evidence=event.evidence,
            last_updated=self._clock(),
            last_confirmed_at=event.created_at,
        )
