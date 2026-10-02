"""The recall stage: long-term memory searched before understanding (ADR-0281).

One orchestration-local stage, of the kind
:class:`~ai_assistant.orchestration.understanding.UnderstandingStage` is: it holds an
injected ``MemoryStore`` and the composition root's threshold, limit and budget, and it
is **not a Protocol**. It calls no model and interprets nothing — it does not decide
that a memory answers anything, is out of date, is relevant or settles a reference
(§3). What it keeps it holds as ids, and the understanding phase fetches them in the
same pass (ADR-0282 §4, §5).

**One cue, per band** (§3). The activation's input text, exactly as the pass holds it,
is the query of one :meth:`~ai_assistant.core.protocols.MemoryStore.search` per band —
``ASSERTED``, ``ATTESTED``, ``DERIVED``, in that order, ADR-0072 §5's precedence — each
over episodic and semantic records, requesting **no eligibility**. From each band's
results, in the store's order, a record is kept only when its ``score`` is at or above
the threshold and the audience predicate admits it, until the limit is filled. A record
returned with no ``score`` is not kept, and ``capped`` is not acted on.

**Past the windows** (ADR-0282 §4). Recall is handed the ids the pass's windows already
hold — the episode window's and the channel window's stored items' — and keeps none of
them: such a record takes no slot, and a further match below it is kept in its place.
Each band's search asks for the limit plus the number of those ids, so the records it
passes over cannot crowd the band out.

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
import math
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
    InputOrigin,
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

#: The one cue recall searches with today (§3).
_CUES: Final = (RecallCue.ACTIVATION_INPUT,)

type RecalledRecord = EpisodicMemory | SemanticMemory


@dataclass(frozen=True, slots=True)
class Recalled:
    """Recall's part of the working episode for one pass (ADR-0282 §4).

    Its decision and each kept item's search score, and no record: the understanding
    phase fetches the kept ids itself (§5).

    Attributes:
        result: What the episode's processing record carries; its items name the kept
            records by id, in recall's order.
        scores: Each kept item's search score, in the items' order; empty unless
            ``result``'s outcome is ``found``.
        error: The ``MemoryStoreError`` or ``TimeoutError`` a ``failed`` or
            ``timed_out`` decision carries, for the controller's stage result
            (ADR-0281 §5).
    """

    result: ActivationRecall
    scores: tuple[float, ...] = ()
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
            ValueError: If ``threshold`` is not finite, ``limit`` is below 1 or above
                ``RECALLED_ITEMS_MAX``, or ``budget`` is not positive.
        """
        if not math.isfinite(threshold):
            msg = "recall's threshold must be a finite number (ADR-0281 §3)"
            raise ValueError(msg)
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

    async def recall(
        self,
        text: str,
        *,
        audience: TurnSupply,
        deadline: float,
        shown: frozenset[str] = frozenset(),
    ) -> Recalled:
        """Search with ``text``, and decide what is kept.

        Args:
            text: The activation's input, exactly as the pass holds it — the one cue.
            audience: The pass's audience posture: its predicate filters what the
                searches return, and an unbounded one searches semantic records alone.
            deadline: The pass's deadline on the running loop's clock, which caps
                recall's budget.
            shown: The stored ids the pass's windows hold, none of which is kept
                (ADR-0282 §4).

        Returns:
            The decision — ``found``, ``nothing_found``, ``failed`` or
            ``timed_out`` — with the kept items and their scores.

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
                kept = await self._search(text, audience, shown)
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
        # Kept only with a score (§3), so each has one.
        scores = tuple(record.score for record in kept if record.score is not None)
        return Recalled(_decision(RecallOutcome.FOUND, items), scores=scores)

    async def _search(
        self, text: str, audience: TurnSupply, shown: frozenset[str]
    ) -> tuple[RecalledRecord, ...]:
        """§3's band-scoped searches, kept in band order until the limit is filled.

        A record the windows hold is passed over before it is judged, so it takes no
        slot, and each search asks for as many more as it may pass over (ADR-0282 §4).
        """
        limit = self._limit + len(shown)
        kinds = (
            (MemoryKind.SEMANTIC,)
            if isinstance(audience, UnboundedAudienceSupply)
            else (MemoryKind.EPISODIC, MemoryKind.SEMANTIC)
        )
        kept: dict[str, RecalledRecord] = {}
        for band in _BANDS:
            found = await self._memory.search(text, limit=limit, kinds=kinds, bands=(band,))
            for record in admitted_to_understanding(audience, found.records):
                if not isinstance(record, EpisodicMemory | SemanticMemory):
                    continue
                if record.id in shown:
                    continue
                # Affirmatively at or above: a NaN score is not, and no score is not.
                if record.score is None or not record.score >= self._threshold:
                    continue
                # A record rewritten into a later band between the searches is kept
                # once, where it was first admitted.
                if record.id in kept:
                    continue
                kept[record.id] = record
                if len(kept) == self._limit:
                    return tuple(kept.values())
        return tuple(kept.values())


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
    """§4's two-value label, and the only provenance judgment recall makes.

    An episode's is read off its trigger's ``origin`` and never off its channel type
    (ADR-0284 §2:3, superseding ADR-0281 §4:4's test): it is ``outside`` exactly where
    the input came from outside.
    """
    if isinstance(record, SemanticMemory):
        outside = rests_on_recorded_external_content(record.provenance)
    else:
        outside = _origin_of(record) is InputOrigin.OUTSIDE
    return RecallProvenance.OUTSIDE if outside else RecallProvenance.USER


def _excerpt_of(record: RecalledRecord) -> str:
    """§6's excerpt, from the stored record and never from this pass's model output.

    **An outside episode's raw input never enters it** (ADR-0284 §2:3, superseding
    ADR-0281 §6:3's channel-type test): an episode whose trigger's ``origin`` is
    ``outside`` gives its latest understanding's meaning, or the fixed text that it
    was a report received on its channel. The user's own input is given where the
    ``origin`` is ``user``; an input whose origin is not recorded is not taken for
    the user's, and gives what an outside one does.
    """
    if isinstance(record, SemanticMemory):
        return record.fact
    processing = record.processing_record
    if processing is None:
        return record.content
    trigger = processing.trigger
    if isinstance(trigger, RecordedChannelTrigger):
        if trigger.origin is InputOrigin.USER:
            payload = trigger.payload
            text = payload.text if isinstance(payload, RecordedTextInput) else payload.transcript
            if text is not None:
                return text
        elif processing.understanding:
            return processing.understanding[-1].meaning
        else:
            channel = trigger.channel
            return (
                "a report received"
                if channel is None
                else f"a report received on {channel.channel_type}:{channel.instance_id}"
            )
    return record.content


def _origin_of(record: EpisodicMemory) -> InputOrigin | None:
    """Who an episode's input came from, as its trigger recorded it (ADR-0284 §2:3)."""
    processing = record.processing_record
    if processing is None or not isinstance(processing.trigger, RecordedChannelTrigger):
        return None
    return processing.trigger.origin
