"""The recall stage: long-term memory searched before understanding (ADR-0281).

One orchestration-local stage, of the kind
:class:`~ai_assistant.orchestration.understanding.UnderstandingStage` is: it holds an
injected ``MemoryStore`` and ``StoryStore`` and the composition root's threshold, limit
and budget, and it is **not a Protocol**. It calls no model and interprets nothing — it
does not decide that a memory answers anything, is out of date, is relevant or settles
a reference (§3). What it keeps it holds as ids, and the understanding phase fetches
them in the same pass (ADR-0282 §4, §5).

**One cue, per band** (§3). The activation's input text, exactly as the pass holds it,
is the query of one :meth:`~ai_assistant.core.protocols.MemoryStore.search` per band —
``ASSERTED``, ``ATTESTED``, ``DERIVED``, in that order, ADR-0072 §5's precedence — each
over episodes and memories, requesting **no eligibility**. From each band's
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
on a pass whose audience posture is unbounded the searches ask for memories
alone, so no episode reaches the pass through recall. The posture is read off the
pass's :data:`~ai_assistant.orchestration.disclosure.TurnSupply` and nothing else.

**The stories of what it keeps** (ADR-0300 §7). For each episode it keeps whose stored
id is an activation's episode, recall reads ``StoryStore.stories_of`` for that
activation — a lookup by identity, never a search — and the item carries those stories
in the order the store returned them. A memory belongs to no story. The
understanding phase hands them to the candidate stories, the item with the higher
search score first (§6:1, :meth:`Recalled.stories`).

**Failure-tolerant** (§5). The searches and the story lookups run under recall's
budget — the smaller of the composition root's budget and the time left before the
pass's deadline. A ``MemoryStoreError``, and a ``StoryStoreError`` the same way
(ADR-0300 §7:3), is a ``failed`` decision and a spent budget a ``timed_out`` one, each
returned with its error rather than raised, so the pass goes on to understanding. Any
other error escapes. The controller that applies §5's continuation is step 3's.

**The second run** (ADR-0308 §2). :meth:`RecallStage.recall_again` is the same stage
run again once understanding has recorded, for planning alone. Its cues are the latest
understanding's ``meaning`` and the ``gap`` of each of its unclear points (ADR-0353
§14:3), each distinct text searched on its own with the band searches above (§2:2). Each cue keeps
records under the same threshold and per-cue limit, passing over what the windows hold
and every record the first run kept, each search asking for the limit plus the number
passed over (§2:3). The cues' records are then kept up to a cap on the total, in band
order: every cue's ``ASSERTED`` records first, then ``ATTESTED``, then ``DERIVED``, and
within a band the meaning's before each gap's, in the order understanding recorded
them. A record more than one cue kept is kept once, its ``found_by`` naming each kind of
cue that kept it (§2:4). The audience rule, the stories of what it keeps, the budget and
the failure tolerance are the first run's (§2:6-§2:7).

**It logs stage and code-owned reason only** — no input, no memory content and no
exception content (ADR-0275 §8).

**What it gives the diagnostic record** (ADR-0314 §4), through the sink the composition
root hands it where the record is on: before its searches, which run it is and its cues;
once they return or fail, each find — its id, its score, the band and the cue whose
search returned it, and whether the audience admitted it — and which were kept, with
the decision's outcome and the failure where there was one.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.diagnostics import failure_body, write_diagnostic
from ai_assistant.core.errors import MemoryStoreError, StoryStoreError
from ai_assistant.core.types import (
    RECALLED_ITEMS_MAX,
    UNDERSTANDING_REFERENT_EXCERPT_CHARS,
    ActivationRecall,
    BeliefBand,
    DiagnosticKind,
    DiagnosticSource,
    EpisodicMemory,
    Memory,
    MemoryKind,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    RecordedTextInput,
    StoryMember,
    StoryMemberKind,
    parties_are_assistants,
    parties_are_persons_own,
    record_attestation,
    record_band,
    record_rests_on_outside_content,
)
from ai_assistant.orchestration.disclosure import (
    UnboundedAudienceSupply,
    admitted_to_understanding,
)
from ai_assistant.orchestration.outside_content import joined_parties, relayed_by
from ai_assistant.orchestration.stories import episode_address
from ai_assistant.orchestration.story_privacy import activation_of

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Container, Mapping, Sequence
    from datetime import timedelta

    from ai_assistant.core.protocols import DiagnosticSink, MemoryStore, StoryStore
    from ai_assistant.core.types import EpisodeProcessingRecord, MemoryRecord
    from ai_assistant.orchestration.disclosure import TurnSupply

__all__ = ["RecallStage", "Recalled", "RecalledRecord"]

_log = structlog.get_logger(__name__)

#: ADR-0072 §5's consumer-side precedence, the order the bands are searched in (§3).
_BANDS: Final = (BeliefBand.ASSERTED, BeliefBand.ATTESTED, BeliefBand.DERIVED)

#: The first run's one cue (§3).
_CUES: Final = (RecallCue.ACTIVATION_INPUT,)

#: The second run's kinds of cue, in the order ``found_by`` names them (ADR-0308 §2:2,
#: ADR-0353 §14:3): ``understood_phrase`` cues nothing now, a version having no
#: references, and stays a member only for the recall records that name it (§14:4).
_SECOND_RUN_CUES: Final = (RecallCue.UNDERSTOOD_MEANING, RecallCue.UNDERSTOOD_GAP)

type RecalledRecord = EpisodicMemory | Memory


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
        error: The ``MemoryStoreError``, ``StoryStoreError`` or ``TimeoutError`` a
            ``failed`` or ``timed_out`` decision carries, for the controller's stage
            result (ADR-0281 §5, ADR-0300 §7:3).
    """

    result: ActivationRecall
    scores: tuple[float, ...] = ()
    error: Exception | None = None

    def stories(self, held: Container[str]) -> tuple[str, ...]:
        """The stories the kept episodes belong to, in ADR-0300 §6:1's order, each once.

        The items are taken the one with the higher search score first, ties in
        recall's own order, and each item's stories in the order it recorded them. Only
        an item ``held`` names contributes: the understanding phase passes the ids its
        fetch admitted, so an episode forgotten or refused by the audience predicate
        since recall kept it brings no candidate, as the window's episodes do not.

        Args:
            held: The kept ids whose records the understanding phase's fetch admitted.

        Returns:
            The story ids, each once, in the order they join the candidates.
        """
        ranked = sorted(
            zip(self.result.items, self.scores, strict=True),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return tuple(
            dict.fromkeys(
                story_id for item, _ in ranked if item.id in held for story_id in item.stories
            )
        )


class RecallStage:
    """Search long-term memory with the activation's input (ADR-0281 §3, §4, §5)."""

    def __init__(  # noqa: PLR0913 — two stores, three composition-root values and the diagnostic sink
        self,
        *,
        memory: MemoryStore,
        stories: StoryStore,
        threshold: float,
        limit: int,
        budget: timedelta,
        diagnostics: DiagnosticSink | None = None,
    ) -> None:
        """Wire the stage to its stores, and to the values the composition root sets.

        Args:
            memory: The store recall searches.
            stories: The story store the kept episodes' stories are looked up in
                (ADR-0300 §7:1).
            threshold: The recall threshold, set for the embedder the composition
                root wires, because a score's scale belongs to its embedder (§3).
            limit: ``RECALL_ITEM_LIMIT``: how many records recall keeps at most.
            budget: ``RECALL_BUDGET``: recall's own budget, before the pass's
                deadline caps it (§5).
            diagnostics: The diagnostic record's write seam (ADR-0314 §4:4), or
                ``None`` where the record is off.

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
        self._stories = stories
        self._threshold = threshold
        self._limit = limit
        self._budget = budget.total_seconds()
        self._diagnostics = diagnostics

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
                searches return, and an unbounded one searches memories alone.
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
        finds = _Finds(noting=self._diagnostics is not None)
        await self._given("first", {text: list(_CUES)})

        async def kept() -> tuple[_Kept, ...]:
            found = await self._search(text, audience, shown, finds)
            return tuple(_Kept(record, _CUES, score) for record, _, score in found)

        return await self._decided(kept, cues=_CUES, deadline=deadline, finds=finds)

    async def recall_again(  # noqa: PLR0913 — the two kinds of cue, the audience, the deadline, what is passed over and the cap
        self,
        meaning: str,
        gaps: Sequence[str],
        *,
        audience: TurnSupply,
        deadline: float,
        passed_over: frozenset[str],
        cap: int,
    ) -> Recalled:
        """The second run: search with what understanding found (ADR-0308 §2).

        Args:
            meaning: The latest understanding's ``meaning``.
            gaps: The ``gap`` of each of its unclear points, in the order understanding
                recorded them (ADR-0353 §14:3).
            audience: The pass's audience posture, as for the first run (§2:6).
            deadline: The pass's deadline on the running loop's clock, which caps
                recall's budget, computed as the first run's is (§2:7).
            passed_over: The stored ids none of which is kept: what the windows hold
                and every record the first run kept (§2:3).
            cap: ``RECALL_SECOND_RUN_CAP``: how many records the run keeps in all
                (§2:4-§2:5).

        Returns:
            The decision, with the kept items, each found by the kinds of cue that
            kept it, and their scores: a record more than one cue kept carries the
            highest of its scores.

        Raises:
            ValueError: If ``cap`` is below 1 or above ``RECALLED_ITEMS_MAX``.
            TimeoutError: If the pass's deadline had already passed, so no search is
                started.
        """
        if not 1 <= cap <= RECALLED_ITEMS_MAX:
            msg = "the second run's cap must be between 1 and RECALLED_ITEMS_MAX (ADR-0308 §2:5)"
            raise ValueError(msg)
        # Each distinct text is one cue, searched once; a text both the meaning and a
        # gap is found by both kinds, at the meaning's place in the order (§2:2).
        cues: dict[str, list[RecallCue]] = {meaning: [RecallCue.UNDERSTOOD_MEANING]}
        for gap in gaps:
            kinds = cues.setdefault(gap, [])
            if RecallCue.UNDERSTOOD_GAP not in kinds:
                kinds.append(RecallCue.UNDERSTOOD_GAP)
        searched = tuple(
            kind for kind in _SECOND_RUN_CUES if any(kind in kinds for kinds in cues.values())
        )

        finds = _Finds(noting=self._diagnostics is not None)
        await self._given("second", cues)

        async def kept() -> tuple[_Kept, ...]:
            found = [
                (tuple(kinds), await self._search(text, audience, passed_over, finds))
                for text, kinds in cues.items()
            ]
            return _capped(found, cap)

        return await self._decided(kept, cues=searched, deadline=deadline, finds=finds)

    async def _given(self, run: str, cues: Mapping[str, Sequence[RecallCue]]) -> None:
        """Write which run this is and its cues, before its searches (ADR-0314 §4)."""
        await write_diagnostic(
            self._diagnostics,
            DiagnosticSource.RECALL,
            DiagnosticKind.GIVEN,
            lambda: {
                "run": run,
                "cues": [
                    {"text": text, "kinds": [kind.value for kind in kinds]}
                    for text, kinds in cues.items()
                ],
            },
        )

    async def _returned(
        self, finds: _Finds, decided: Recalled | None, error: Exception | None = None
    ) -> None:
        """Write each find and which were kept, once the searches returned or failed."""

        def body() -> dict[str, object]:
            returned: dict[str, object] = {"finds": list(finds.found)}
            if decided is not None:
                returned["outcome"] = decided.result.outcome.value
                scores: Sequence[float | None] = decided.scores or (None,) * len(
                    decided.result.items
                )
                returned["kept"] = [
                    {
                        "id": item.id,
                        "score": _score(score),
                        "found_by": [kind.value for kind in item.found_by],
                    }
                    for item, score in zip(decided.result.items, scores, strict=True)
                ]
            failed = error if error is not None else (None if decided is None else decided.error)
            if failed is not None:
                returned["failure"] = failure_body(failed)
            return returned

        await write_diagnostic(
            self._diagnostics, DiagnosticSource.RECALL, DiagnosticKind.RETURNED, body
        )

    async def _decided(
        self,
        kept_by: Callable[[], Awaitable[tuple[_Kept, ...]]],
        *,
        cues: tuple[RecallCue, ...],
        deadline: float,
        finds: _Finds,
    ) -> Recalled:
        """Run one recall, and write what it returned or how it failed (ADR-0314 §4).

        Raises:
            TimeoutError: If the pass's deadline had already passed, so no search is
                started. That is the pass's deadline, not recall's budget (§5).
        """
        try:
            decided = await self._deciding(kept_by, cues=cues, deadline=deadline)
        except Exception as exc:
            await self._returned(finds, None, exc)
            raise
        await self._returned(finds, decided)
        return decided

    async def _deciding(
        self,
        kept_by: Callable[[], Awaitable[tuple[_Kept, ...]]],
        *,
        cues: tuple[RecallCue, ...],
        deadline: float,
    ) -> Recalled:
        """Run one recall's searches and story lookups under its budget, and decide (§5).

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
                kept = await kept_by()
                stories = [await self._stories_of(one.record) for one in kept]
        except MemoryStoreError as error:
            _log.warning("recall_failed", stage="recall", reason="memory_store_error")
            return Recalled(_decision(RecallOutcome.FAILED, cues=cues), error=error)
        except StoryStoreError as error:
            # ADR-0300 §7:3: handled as a MemoryStoreError is.
            _log.warning("recall_failed", stage="recall", reason="story_store_error")
            return Recalled(_decision(RecallOutcome.FAILED, cues=cues), error=error)
        except TimeoutError as error:
            if not budget.expired():
                # Not recall's budget: an error the stage does not handle (§5).
                raise
            _log.warning("recall_failed", stage="recall", reason="budget_spent")
            return Recalled(_decision(RecallOutcome.TIMED_OUT, cues=cues), error=error)
        if not kept:
            return Recalled(_decision(RecallOutcome.NOTHING_FOUND, cues=cues))
        items = tuple(
            _item(one.record, of, found_by=one.found_by)
            for one, of in zip(kept, stories, strict=True)
        )
        scores = tuple(one.score for one in kept)
        return Recalled(_decision(RecallOutcome.FOUND, items, cues=cues), scores=scores)

    async def _search(
        self, text: str, audience: TurnSupply, shown: frozenset[str], finds: _Finds
    ) -> tuple[tuple[RecalledRecord, BeliefBand, float], ...]:
        """§3's band-scoped searches, kept in band order until the limit is filled.

        A record the windows hold is passed over before it is judged, so it takes no
        slot, and each search asks for as many more as it may pass over (ADR-0282 §4).
        Each kept record comes with the band whose search kept it and its score. Every
        record a search returns is noted in ``finds`` for the diagnostic record.
        """
        limit = self._limit + len(shown)
        kinds = (
            (MemoryKind.MEMORY,)
            if isinstance(audience, UnboundedAudienceSupply)
            else (MemoryKind.EPISODIC, MemoryKind.MEMORY)
        )
        kept: dict[str, tuple[RecalledRecord, BeliefBand, float]] = {}
        for band in _BANDS:
            found = await self._memory.search(text, limit=limit, kinds=kinds, bands=(band,))
            admitted = admitted_to_understanding(audience, found.records)
            finds.note(text, band, found.records, admitted)
            for record in admitted:
                if record.id in shown:
                    continue
                # Affirmatively at or above: a NaN score is not, and no score is not.
                score = record.score
                if score is None or not score >= self._threshold:
                    continue
                # A record rewritten into a later band between the searches is kept
                # once, where it was first admitted.
                if record.id in kept:
                    continue
                kept[record.id] = (record, band, score)
                if len(kept) == self._limit:
                    return tuple(kept.values())
        return tuple(kept.values())

    async def _stories_of(self, record: RecalledRecord) -> tuple[str, ...]:
        """The stories a kept episode belongs to directly, as the store returns them.

        ADR-0300 §7:1: read only for an episode whose stored id is its activation's
        episode — the activation read off its processing record and its address
        compared with the id, never parsed out of it. A memory, and an
        episode recording no activation or stored at another address, belong to no story,
        so nothing is read for them.
        """
        if not isinstance(record, EpisodicMemory):
            return ()
        activation = activation_of(record)
        if activation is None or record.id != episode_address(activation):
            return ()
        member = StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation)
        return tuple(header.story_id for header in await self._stories.stories_of(member))


class _Finds:
    """What one recall's searches returned, noted for the diagnostic record (§4).

    Notes nothing where the record is off, so no entry's body is built (ADR-0314 §2:1).
    """

    def __init__(self, *, noting: bool) -> None:
        self._noting = noting
        self.found: list[dict[str, object]] = []

    def note(
        self,
        cue: str,
        band: BeliefBand,
        records: Sequence[MemoryRecord],
        admitted: Sequence[MemoryRecord],
    ) -> None:
        """Note each record one search returned, in the store's order."""
        if not self._noting:
            return
        let_in = {record.id for record in admitted}
        self.found.extend(
            {
                "id": record.id,
                "score": _score(record.score),
                "band": band.value,
                "cue": cue,
                "admitted": record.id in let_in,
            }
            for record in records
        )


def _score(score: float | None) -> float | None:
    """A score as JSON holds it: a non-finite one is no score."""
    return score if score is not None and math.isfinite(score) else None


@dataclass(frozen=True, slots=True)
class _Kept:
    """One record a run keeps: the kinds of cue that kept it, and its search score."""

    record: RecalledRecord
    found_by: tuple[RecallCue, ...]
    score: float


def _capped(
    found: Sequence[
        tuple[tuple[RecallCue, ...], tuple[tuple[RecalledRecord, BeliefBand, float], ...]]
    ],
    cap: int,
) -> tuple[_Kept, ...]:
    """The second run's records, kept up to ``cap`` in band order (ADR-0308 §2:4).

    ``found`` is each cue's kept records, in cue order: the meaning's first, then each
    gap's in the order understanding recorded them. Every cue's ``ASSERTED`` records
    come first, then ``ATTESTED``, then ``DERIVED``, and within a band the cues in that
    order, each cue's records in the order its search kept them. A record more than one
    cue kept is kept once, where it first falls, its ``found_by`` naming each kind of
    cue that kept it, in :class:`~ai_assistant.core.types.RecallCue`'s order, and its
    score the highest any of them gave it.
    """
    kinds: dict[str, set[RecallCue]] = {}
    scores: dict[str, float] = {}
    for by, records in found:
        for record, _, score in records:
            kinds.setdefault(record.id, set()).update(by)
            scores[record.id] = max(score, scores.get(record.id, score))
    ordered: dict[str, RecalledRecord] = {}
    for band in _BANDS:
        for _, records in found:
            for record, kept_in, _ in records:
                if kept_in is band and record.id not in ordered:
                    ordered[record.id] = record
    return tuple(
        _Kept(
            record,
            tuple(kind for kind in _SECOND_RUN_CUES if kind in kinds[record.id]),
            scores[record.id],
        )
        for record in tuple(ordered.values())[:cap]
    )


def _decision(
    outcome: RecallOutcome,
    items: tuple[RecalledItem, ...] = (),
    *,
    cues: tuple[RecallCue, ...] = _CUES,
) -> ActivationRecall:
    return ActivationRecall(outcome=outcome, cues=cues, items=items)


def _item(
    record: RecalledRecord, stories: tuple[str, ...], *, found_by: tuple[RecallCue, ...] = _CUES
) -> RecalledItem:
    """One kept record as the processing record carries it (§6, ADR-0300 §7:2)."""
    # ADR-0328 §2:5-§2:6: a memory's item names the memory kind and carries its band,
    # its computed rests-on-outside-content and its standing's source details.
    return RecalledItem(
        kind=MemoryKind(record.kind),
        id=record.id,
        excerpt=_excerpt_of(record)[:UNDERSTANDING_REFERENT_EXCERPT_CHARS],
        provenance=_provenance_of(record),
        standing=record_band(record),
        rests_on_recorded_external_content=record_rests_on_outside_content(record),
        attestation=record_attestation(record),
        found_by=found_by,
        stories=stories,
    )


def _provenance_of(record: RecalledRecord) -> RecallProvenance:
    """§4's two-value label, and the only provenance judgment recall makes.

    An episode's is read off its inputs' parties, with their relay marks, and never off
    its channel type (ADR-0284 §2:3 as ADR-0351 §8:2 amends it, superseding ADR-0281
    §4:4's test): a channel activation's episode is ``user`` exactly where every input it
    holds is the user's own (:func:`_users_own`), and an input whose parties are unknown
    is not taken for the user's — the same reading :func:`_excerpt_of` makes, so the
    label and the excerpt never disagree; an input that is the assistant's is not the
    user's either (ADR-0350 §6:12), and nor is one understanding marked relayed
    (ADR-0351 §5:7). A resume has no input (§2:4) and an episode with no processing
    record no trigger, and both are ``user``, as ADR-0281 §4:4 labelled them.
    """
    if isinstance(record, Memory):
        outside = record.rests_on_outside_content
    else:
        processing = record.processing_record
        outside = processing is not None and not _users_own(processing)
    return RecallProvenance.OUTSIDE if outside else RecallProvenance.USER


def _users_own(processing: EpisodeProcessingRecord) -> bool:
    """Whether every input an episode holds is the user's own (ADR-0351 §5:2, §5:7, §8:5).

    Its trigger's, by its parties and its latest understanding version's relay mark,
    and each joined input's, by its parties and its own. A joined input whose parties are
    empty, an approval's, is left out (ADR-0361 §6:6).
    """
    return parties_are_persons_own(
        processing.trigger.parties, relayed=relayed_by(processing.understanding)
    ) and all(
        parties_are_persons_own(parties, relayed=one.relayed)
        for one in processing.joined
        if (parties := joined_parties(one)) != ()
    )


def _excerpt_of(record: RecalledRecord) -> str:
    """§6's excerpt, from the stored record and never from this pass's model output.

    **An outside episode's raw input never enters it** (ADR-0284 §2:3, superseding
    ADR-0281 §6:3's channel-type test): an episode holding an input that is not the
    user's own gives its latest understanding's meaning, or the fixed text that it was
    a report received on its channel. The user's own input is given where every input
    it holds is the user's own, read with its relay mark (ADR-0351 §5:4, §5:7); an
    input whose parties are unknown is not taken for the user's, and gives what an
    outside one does. An input that is the assistant's, a scheduled task's instruction,
    is not the user's either (ADR-0350 §6:12): it gives its meaning, or the fixed text
    that it was work the assistant scheduled.
    """
    if isinstance(record, Memory):
        return record.content
    processing = record.processing_record
    if processing is None:
        return record.content
    trigger = processing.trigger
    if _users_own(processing):
        payload = trigger.payload
        text = payload.text if isinstance(payload, RecordedTextInput) else payload.transcript
        if text is not None:
            return text
    elif processing.understanding:
        return processing.understanding[-1].meaning
    else:
        channel = trigger.channel
        what = (
            "work the assistant scheduled"
            if parties_are_assistants(trigger.parties, relayed=relayed_by(processing.understanding))
            else "a report received"
        )
        return (
            what if channel is None else f"{what} on {channel.channel_type}:{channel.instance_id}"
        )
    return record.content
