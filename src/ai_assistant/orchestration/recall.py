"""The recall stage: long-term memory searched before understanding (ADR-0281).

One orchestration-local stage, of the kind
:class:`~ai_assistant.orchestration.understanding.UnderstandingStage` is: it holds an
injected ``MemoryStore`` and the composition root's threshold, limit and budget, and it
is **not a Protocol**. It calls no model and interprets nothing — it does not decide
that a memory answers anything, is out of date, is relevant or settles a reference
(§3). What it keeps, the understanding stage reads in the same pass (§7).

**One cue, per band** (§3). The activation's input text, exactly as the pass holds it,
is the query of one :meth:`~ai_assistant.core.protocols.MemoryStore.search` per band —
``ASSERTED``, ``ATTESTED``, ``DERIVED``, in that order, ADR-0072 §5's precedence — each
over episodic and semantic records, bounded by the limit, requesting **no
eligibility**. From each band's results, in the store's order, a record is kept only
when its ``score`` is at or above the threshold and the audience predicate admits it,
until the limit is filled. A record returned with no ``score`` is not kept, and
``capped`` is not acted on.

**Audience** (§4). ``admitted_to_understanding`` — the predicate of the understanding
stage's two windows — filters what the searches returned before anything is kept, and
on a pass whose audience posture is unbounded the searches ask for semantic records
alone, so no episode reaches the pass through recall. The posture is read off the
pass's :data:`~ai_assistant.orchestration.disclosure.TurnSupply` and nothing else.

**Failure-tolerant** (§5). The searches run under recall's budget — the smaller of the
composition root's budget and the time left before the pass's deadline. A
``MemoryStoreError`` is a ``failed`` decision and a spent budget a ``timed_out`` one,
each returned with its error rather than raised, so the pass goes on to understanding.
Any other error escapes. The controller that applies §5's continuation is step 3's.

**It logs stage and code-owned reason only** — no input, no memory content and no
exception content (ADR-0275 §8).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    RECALLED_ITEMS_MAX,
    UNDERSTANDING_REFERENT_EXCERPT_CHARS,
    ActivationRecall,
    BeliefBand,
    EpisodicMemory,
    MemoryKind,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    SemanticMemory,
    band_of,
    rests_on_recorded_external_content,
)
from ai_assistant.orchestration.disclosure import (
    UnboundedAudienceSupply,
    admitted_to_understanding,
)

if TYPE_CHECKING:
    from datetime import timedelta

    from ai_assistant.core.protocols import MemoryStore
    from ai_assistant.orchestration.disclosure import TurnSupply

__all__ = ["RecallStage", "Recalled", "RecalledRecord"]

_log = structlog.get_logger(__name__)

#: ADR-0072 §5's consumer-side precedence, the order the bands are searched in (§3).
_BANDS: Final = (BeliefBand.ASSERTED, BeliefBand.ATTESTED, BeliefBand.DERIVED)

#: The channel type whose input is a report received (ADR-0274 §7, ADR-0281 §4).
_EVENT_CHANNEL: Final = "informational_event"

#: The one cue recall searches with today (§3).
_CUES: Final = (RecallCue.ACTIVATION_INPUT,)

type RecalledRecord = EpisodicMemory | SemanticMemory


@dataclass(frozen=True, slots=True)
class Recalled:
    """Recall's decision for one pass, and the records it kept (ADR-0281 §6).

    Attributes:
        result: What the episode's processing record carries.
        records: The kept records, in recall's order, for the understanding stage to
            render. Held for the pass and never persisted; empty unless ``result``'s
            outcome is ``found``.
        error: The ``MemoryStoreError`` or ``TimeoutError`` a ``failed`` or
            ``timed_out`` decision carries, for the controller's stage result (§5).
    """

    result: ActivationRecall
    records: tuple[RecalledRecord, ...] = ()
    error: Exception | None = None


class RecallStage:
    """Search long-term memory with the activation's input (ADR-0281 §3, §4, §5)."""

    def __init__(
        self, *, memory: MemoryStore, threshold: float, limit: int, budget: timedelta
    ) -> None:
        """Wire the stage to its store, and to the values the composition root sets.

        Args:
            memory: The store recall searches.
            threshold: The recall threshold, set for the embedder the composition
                root wires, because a score's scale belongs to its embedder (§3).
            limit: ``RECALL_ITEM_LIMIT``: how many records recall keeps at most.
            budget: ``RECALL_BUDGET``: recall's own budget, before the pass's
                deadline caps it (§5).

        Raises:
            ValueError: If ``limit`` is below 1 or above ``RECALLED_ITEMS_MAX``, or
                ``budget`` is not positive.
        """
        if not 1 <= limit <= RECALLED_ITEMS_MAX:
            msg = "recall's limit must be between 1 and RECALLED_ITEMS_MAX (ADR-0281 §3, §6)"
            raise ValueError(msg)
        if budget.total_seconds() <= 0:
            msg = "recall's budget must be positive (ADR-0281 §5)"
            raise ValueError(msg)
        self._memory = memory
        self._threshold = threshold
        self._limit = limit
        self._budget = budget.total_seconds()

    async def recall(self, text: str, *, audience: TurnSupply, deadline: float) -> Recalled:
        """Search with ``text``, and decide what is kept.

        Args:
            text: The activation's input, exactly as the pass holds it — the one cue.
            audience: The pass's audience posture: its predicate filters what the
                searches return, and an unbounded one searches semantic records alone.
            deadline: The pass's deadline on the running loop's clock, which caps
                recall's budget.

        Returns:
            The decision — ``found``, ``nothing_found``, ``failed`` or
            ``timed_out`` — with the kept records.

        Raises:
            TimeoutError: If the pass's deadline had already passed, so no search is
                started. That is the pass's deadline, not recall's budget (§5).
        """
        loop = asyncio.get_running_loop()
        now = loop.time()
        if deadline <= now:
            msg = "the pass's deadline passed before recall"
            raise TimeoutError(msg)
        budget = asyncio.timeout_at(min(now + self._budget, deadline))
        try:
            async with budget:
                kept = await self._search(text, audience)
        except MemoryStoreError as error:
            _log.warning("recall_failed", stage="recall", reason="memory_store_error")
            return Recalled(_decision(RecallOutcome.FAILED), error=error)
        except TimeoutError as error:
            if not budget.expired():
                # Not recall's budget: an error the stage does not handle (§5).
                raise
            _log.warning("recall_failed", stage="recall", reason="budget_spent")
            return Recalled(_decision(RecallOutcome.TIMED_OUT), error=error)
        if not kept:
            return Recalled(_decision(RecallOutcome.NOTHING_FOUND))
        items = tuple(_item(record) for record in kept)
        return Recalled(_decision(RecallOutcome.FOUND, items), records=kept)

    async def _search(self, text: str, audience: TurnSupply) -> tuple[RecalledRecord, ...]:
        """§3's band-scoped searches, kept in band order until the limit is filled."""
        kinds = (
            (MemoryKind.SEMANTIC,)
            if isinstance(audience, UnboundedAudienceSupply)
            else (MemoryKind.EPISODIC, MemoryKind.SEMANTIC)
        )
        kept: list[RecalledRecord] = []
        for band in _BANDS:
            found = await self._memory.search(text, limit=self._limit, kinds=kinds, bands=(band,))
            for record in admitted_to_understanding(audience, found.records):
                if not isinstance(record, EpisodicMemory | SemanticMemory):
                    continue
                if record.score is None or record.score < self._threshold:
                    continue
                kept.append(record)
                if len(kept) == self._limit:
                    return tuple(kept)
        return tuple(kept)


def _decision(outcome: RecallOutcome, items: tuple[RecalledItem, ...] = ()) -> ActivationRecall:
    return ActivationRecall(outcome=outcome, cues=_CUES, items=items)


def _item(record: RecalledRecord) -> RecalledItem:
    """One kept record as the processing record carries it (§6)."""
    provenance = record.provenance
    return RecalledItem(
        kind=MemoryKind(record.kind),
        id=record.id,
        excerpt=_excerpt_of(record)[:UNDERSTANDING_REFERENT_EXCERPT_CHARS],
        provenance=_provenance_of(record),
        standing=band_of(provenance.source),
        rests_on_recorded_external_content=rests_on_recorded_external_content(provenance),
        attestation=provenance.attestation,
        found_by=_CUES,
    )


def _provenance_of(record: RecalledRecord) -> RecallProvenance:
    """§4's two-value label, and the only provenance judgment recall makes."""
    if isinstance(record, SemanticMemory):
        outside = rests_on_recorded_external_content(record.provenance)
    else:
        outside = _event_channel(record) is not None
    return RecallProvenance.OUTSIDE if outside else RecallProvenance.USER


def _excerpt_of(record: RecalledRecord) -> str:
    """§6's excerpt, from the stored record and never from this pass's model output.

    **An outside episode's raw input never enters it**: an informational event's
    episode gives its latest understanding's meaning, or the fixed text that it was a
    report received on its channel.
    """
    if isinstance(record, SemanticMemory):
        return record.fact
    channel = _event_channel(record)
    if channel is not None:
        processing = record.processing_record
        if processing is not None and processing.understanding:
            return processing.understanding[-1].meaning
        return f"a report received on {channel}"
    processing = record.processing_record
    if processing is not None and isinstance(processing.trigger, RecordedChannelTrigger):
        payload = processing.trigger.payload
        text = payload.text if isinstance(payload, RecordedTextInput) else payload.transcript
        if text is not None:
            return text
    return record.content


def _event_channel(record: EpisodicMemory) -> str | None:
    """The informational event channel an episode's trigger arrived on, if it did."""
    processing = record.processing_record
    if processing is None:
        return None
    channel = processing.trigger.channel
    if channel is None or channel.channel_type != _EVENT_CHANNEL:
        return None
    return f"{channel.channel_type}:{channel.instance_id}"
