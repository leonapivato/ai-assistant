r"""The consolidation stage: a chunked walk that distils records into beliefs.

Leg 7's producer — "many episodes distilled into few durable beliefs, run by the
hub's scheduler". It walks the memory store a bounded chunk at a time (ADR-0114),
asks a model what the chunk justifies believing, computes the derived-taint marker
from the inputs **it** selected, and routes every proposal through the
orchestration write stage (ADR-0106 §6).

**Why the whole stage lives here, producer included.** ADR-0106 §3 puts the taint
computation on "the component that **selected the input set**" and declines to
name a module for the producer, precisely so this is not settled by implication:
"ADR-0077 §1's 'Selection therefore belongs to `orchestration`' is a ruling about
the observer's stage and this ADR does not extend it by implication to a scheduler
job nobody has designed." The observer's shape — a producer in `learning` behind
an `Observer` Protocol — is not available without a third piece of
`core/protocols.py` surface, and ADR-0114 decides two operations and two types and
says so in terms. ADR-0028 §7 refuses a generic seam until a second implementation
exists, so the producer is module-private here and reaches the LLM only through
the ratified :class:`~ai_assistant.core.protocols.ModelProvider` seam (golden rule
4: no provider SDK is imported). A second consolidator is what promotes it.

Four boundaries, three of them the observer's and one this stage's alone:

- **The citations are ours, never the model's.** The prompt labels each record and
  the model cites labels; every label is mapped back to the id of the record this
  stage actually read (ADR-0047 §2). A model that can write an id can write one
  for a record it never saw.
- **The confidence is ours, never the model's**, and is a pure function of the
  epistemic step and the count of distinct supports, so re-consolidating the same
  material cannot inflate a belief through the fold's maximum.
- **The band is ours and is an absolute.** A consolidation is proposed
  ``OBSERVED`` or ``INFERRED`` — never ``ATTESTED``, never ``USER_ASSERTED`` —
  whatever the bands of its inputs (ADR-0106 §5).
- **The taint marker is ours, and the producer's value is discarded rather than
  merged** (ADR-0106 §3). That is fail-closed against a producer that forgets,
  because the producer never had the choice: the failure that matters is not a
  producer over-claiming taint but one omitting it, and nothing guarantees a field
  in a model's output.

The envelope schema below is this implementation's, not a ratified seam: a second
consolidator would legitimately prompt differently, exactly as a second
``Observer`` or ``Planner`` would.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from pydantic import ValidationError

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import FoldOntoCitedRecordError
from ai_assistant.core.types import (
    DeferralAdmissionOutcome,
    MemoryDecisionKind,
    MemorySource,
    MemoryUpdateProposal,
    Message,
    PreferenceMemory,
    ProceduralMemory,
    Provenance,
    Role,
    SemanticMemory,
    rests_on_recorded_external_content,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryStore, ModelProvider
    from ai_assistant.core.types import MemoryRecord
    from ai_assistant.orchestration.writes import MemoryWriteStage

#: The walk this job advances. One name identifies the (job, order) pair ADR-0111
#: §1 describes, and the store never interprets or normalises it (ADR-0114 §5).
CONSOLIDATION_WALK: Final = "consolidation"

#: Defaults for the two bounds ADR-0111 §4 names and the proposal cap. All three
#: are also composition-root arguments, so an operator's ``Settings`` values win;
#: these are what the class does when nobody says.
DEFAULT_CHUNK_SIZE: Final = 50
DEFAULT_RUN_BUDGET: Final = timedelta(minutes=5)
DEFAULT_MAX_PROPOSALS: Final = 5

#: This producer's confidence ladder, in ``ModelBackedObserver``'s shape and for
#: its reasons (ADR-0077 §5): strictly below 1.0 always, ``OBSERVED`` above
#: ``INFERRED`` on equal support, non-decreasing in support, under a ceiling, and a
#: pure function of those two inputs alone. The figures sit one notch below the
#: observer's because a consolidation generalises over records that were themselves
#: derived, so it stands one inference further from what was actually seen.
_LADDER: Final[dict[MemorySource, tuple[float, float]]] = {
    MemorySource.OBSERVED: (0.50, 0.80),
    MemorySource.INFERRED: (0.30, 0.65),
}
_SUPPORT_INCREMENT: Final = 0.05

#: How many distinct supporting records each step needs before a belief may be
#: proposed at all. A consolidation exists to generalise over *many* records, so
#: both floors sit above the observer's: a "consolidation" resting on one record is
#: a copy of that record, and an inference from two is the single-instance
#: hardening ADR-0005 §Context names, one hop along.
_EVIDENCE_FLOOR: Final[dict[MemorySource, int]] = {
    MemorySource.OBSERVED: 2,
    MemorySource.INFERRED: 3,
}

#: The record kinds a consolidation may propose. ``EPISODIC`` is absent by
#: decision: an episode is a record that something happened, and only the
#: deterministic capture path present at the time may write one (ADR-0077 §2,
#: ADR-0093 §4).
_PROPOSABLE_KINDS: Final = frozenset({"semantic", "preference", "procedural"})

#: How many decode misses :func:`_entries` tolerates before giving up, for
#: ``planning.planner``'s reason: a failed ``raw_decode`` costs work proportional
#: to how far into the reply it reached, so attempting one at every brace of a
#: brace-dense reply is quadratic and blocks the event loop.
_MAX_EXTRACTION_MISSES: Final = 256

#: How much of one record's content the prompt carries. A consolidation chunk is
#: fifty records by default and every one of them is an egress of Tier 1 material,
#: so the batch is bounded in bytes as well as in count — ``observation_batch_size``
#: is "both a prompt and an egress" (ADR-0111 §4) and this batch is larger.
_CONTENT_BUDGET: Final = 400

#: What a proposal's rationale says when the model supplied none usable. A
#: rationale is non-blank by contract, and inventing a specific justification the
#: model did not give would be worse than saying plainly where the belief came
#: from.
_DEFAULT_RATIONALE: Final = "consolidated from stored records"

_SYSTEM_PROMPT = """\
You are the consolidation stage of an AI assistant. You are shown a batch of \
records the assistant already holds, and you propose the few durable beliefs that \
this material justifies as a whole.

Consolidate: say what the batch shows *taken together* that no single record \
states. Do not restate one record. Do not summarise the batch. Proposing nothing \
is a perfectly good answer, and is the right one when the records have no common \
thread.

Propose a belief only when it is ABOUT THE USER and would change a later answer: \
a preference, a durable fact about them or their world, a workflow they follow.

Each belief takes one of two epistemic steps:
- "observed" — the cited records directly show it. Cite at least TWO.
- "inferred" — you generalised beyond what the records show. Cite at least THREE.

Cite records by the labels in brackets, exactly as they appear. Never invent a \
label, and never cite one that is not in the batch.

Reply with a single JSON object and nothing else — no prose, no code fence:

{"beliefs": [
   {"kind": "semantic" | "preference" | "procedural",
    "step": "observed" | "inferred",
    "content": "<the belief, in one sentence>",
    "evidence": ["<label>", ...],
    "rationale": "<why the cited records justify it>",
    "steps": ["<ordered step>", ...]}
 ]}

`beliefs` must be a list, and may be empty. `steps` applies to a "procedural" \
belief only and is otherwise ignored. Do not include ids, confidence values, \
timestamps, or any claim about where the material came from; those are assigned \
downstream."""


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _confidence(step: MemorySource, supports: int) -> float:
    """This producer's confidence for ``supports`` distinct records taken by ``step``.

    Pure in exactly those two inputs, so the same material yields the same number
    however many times it is consolidated — which is what closes the repetition
    route to inflation when ADR-0111 §3's at-least-once walk re-processes a chunk
    and the gate folds the result as a ``REINFORCE`` taking the maximum.
    """
    base, ceiling = _LADDER[step]
    return min(base + _SUPPORT_INCREMENT * (supports - 1), ceiling)


@dataclass(frozen=True, slots=True)
class ConsolidationReport:
    """What one scheduled consolidation run did (ADR-0111 §9).

    A frozen ``orchestration`` dataclass rather than a ``core`` model, for
    :class:`~ai_assistant.orchestration.writes.WriteOutcome`'s reason: it crosses
    no *subsystem* boundary. Every field is Tier 2 — counts and two dispositions,
    no belief text and no record id — so it is loggable under ADR-0004 §5, which
    is why an ``ObservationReport``-shaped result naming beliefs is not what a
    scheduled run returns.

    Attributes:
        chunks: How many chunks this run processed and recorded as done.
        examined: How many records those chunks yielded to selection.
        proposed: How many proposals reached the write stage.
        committed: How many earned a committing ruling.
        deferred: How many became a question the queue accepted — admitted, or
            suppressed as a duplicate of one already pending. Both are disposals:
            the proposal is represented by a question the user can answer, which
            is what separates them from the refusal that halts a run (#811).
        rejected: How many the gate refused outright.
        discarded_unusable: Model output that could not be used, counted rather
            than repaired, re-prompted for, or invented around (ADR-0077 §4).
        refused_self_citing: Proposals the write path refused because the policy
            would have folded them onto a record they cite (ADR-0116 §2's
            policy-chosen arm). Counted rather than absorbed silently, because a
            refusal without a number is indistinguishable from a producer that
            proposed nothing (§4). The producer-chosen arm is **not** counted here
            — it propagates and ends the run.
        discarded_over_limit: Usable beliefs dropped because the chunk was already
            at ``max_proposals``. Counted separately from the unusable ones and
            never folded into them: the two are different facts about a run, and a
            capped reply that reported neither would be indistinguishable from a
            model that honestly proposed exactly the cap — which is the confusion
            this counting exists to remove (ADR-0077 §2, §4).
        exhausted: Whether the walk reached the end of the store. ``False`` on a
            run that spent its budget or halted, and the two are distinguishable
            through :attr:`halted`.
        halted: Whether the run stopped at a chunk it could not record as done
            (ADR-0111 §5). A completed run that did not exhaust its work, never a
            failure — recording it as one would make a queue at its cap
            indistinguishable from a broken store (ADR-0111 §9).
    """

    chunks: int = 0
    examined: int = 0
    proposed: int = 0
    committed: int = 0
    deferred: int = 0
    rejected: int = 0
    discarded_unusable: int = 0
    discarded_over_limit: int = 0
    refused_self_citing: int = 0
    exhausted: bool = False
    halted: bool = False


class ConsolidationStage:
    """Walks the store in chunks and distils each chunk into durable beliefs."""

    def __init__(  # noqa: PLR0913 — three injected collaborators plus the three bounds and the seams
        self,
        *,
        memory: MemoryStore,
        writes: MemoryWriteStage,
        model: ModelProvider,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        run_budget: timedelta = DEFAULT_RUN_BUDGET,
        max_proposals: int = DEFAULT_MAX_PROPOSALS,
        now: Clock = _utcnow,
        id_factory: Callable[[], str] = _uuid,
        walk: str = CONSOLIDATION_WALK,
    ) -> None:
        """Wire the stage from injected contracts.

        Two obligations no type can express, so each is the composition root's
        (ADR-0028 §4's shape, as :class:`ObservationStage` states its three):

        * **``memory`` must be the store the write stage's writer persists to.**
          Wired to a second store, this walks records the write path cannot cite
          and every proposal is refused for unresolved evidence — the silent
          failure ADR-0114's Alternatives give as the decisive reason the walk sits
          on ``MemoryStore`` rather than beside it.
        * **``model`` must not fall back.** ADR-0077 §3's rule reads here with more
          force than it does on observation: a consolidation prompt carries a whole
          chunk of stored records, so widening the set of providers that see one
          buys reliability for work that is deferrable by construction — the next
          run re-reads the chunk, because this one will not have recorded it as
          done. That is a property of the provider the composition root builds;
          this class cannot enforce it and does not pretend to.

        Args:
            memory: The store this walks, through the ``MemoryStore`` contract.
            writes: The orchestration write stage. **The only route to the store's
                write path** (ADR-0106 §6): a job calling ``MemoryWriter.ingest``
                directly would rule ``ASK_USER`` on a thousand consolidations and
                persist not one question, because the writer writes nothing on that
                ruling and the *stage* is what enqueues.
            model: The model seam that reads each chunk. The only dependency on the
                LLM; no provider SDK is imported (golden rule 4).
            chunk_size: How many records one chunk examines (ADR-0111 §4). Passed
                to the store, which refuses anything that is not exactly an ``int``
                in ``[1, 2**63)``, so this class adds no second bound of its own.
            run_budget: How long the run may spend before returning with work
                remaining. Checked **at a chunk boundary**, so no chunk is
                abandoned part-way and a run overruns by at most one chunk.
            max_proposals: The most proposals one chunk may yield. Beyond it they
                are discarded and counted, never queued.
            now: Clock for the budget and each proposal's ``last_updated``;
                injectable for deterministic tests and guarded by
                :func:`~ai_assistant.core.clock.checked_clock` (ADR-0026 §7).
            id_factory: Mints the id of every proposed record; injectable so tests
                assert exact ids (ADR-0047 §2).
            walk: The walk name whose position this job advances. One job, one
                name; a second consolidating job would take a second (ADR-0111 §1).
        """
        self._memory = memory
        self._writes = writes
        self._model = model
        self._chunk_size = chunk_size
        self._run_budget = run_budget
        self._max_proposals = max_proposals
        self._clock = checked_clock(now, owner="ConsolidationStage")
        self._id_factory = id_factory
        self._walk = walk

    async def run(self) -> ConsolidationReport:
        """Consolidate chunks until the work is exhausted or the budget is spent.

        **The cursor advances strictly after the chunk's effects, never before**,
        which is the ordering ADR-0111 §3 obliges and ADR-0114 §3 states as a
        caller precondition no store can enforce. It is two calls in one loop here
        precisely so a reviewer and a test can see it, rather than an invariant
        spread across a store and a scheduler. Anything raising between the two —
        a model failure, a store error, a cancellation at shutdown — leaves the
        recorded position unchanged, so the chunk is re-processed on the next run.

        **A refused question halts the run** (ADR-0111 §5) and the chunk is *not*
        recorded as done, so its material is retained and re-proposed later rather
        than consumed (ADR-0106 §6). Halting also stops the run spending further
        model calls producing questions for a queue that has already answered
        ``REFUSED`` because it is at its cap — a condition nothing but a user
        answering will clear, so it cannot change part-way through a run.

        **A generalisation the policy folds onto one of its own citations is a
        refusal this run survives.** ADR-0081 §1 refuses a write landing at an id
        the proposal cites, and a consolidator reaches it by behaving correctly:
        it cites what it consolidated, generalises over that, and the policy may
        rule ``REINFORCE`` onto one of the cited records. ADR-0116 §2 gives that
        arm its own class, so :meth:`_route` counts the proposal and carries on
        (§4) and this run records its chunk as done (§5). Left as a bare store
        error it was a deterministic stall — the same failure every run, forever,
        with no backoff under ADR-0111 §6 — which is what ADR-0116 exists to fix.

        **The producer-chosen arm is not caught and ends the run**, which is
        ADR-0116 §4's second clause: an id this stage minted *and* cited is a bug
        in this stage, so it propagates and ADR-0111 §5's halt applies.

        **A run still does not consolidate what it has just produced**, and that is
        now an optimisation rather than the mechanism. A committed consolidation is
        a new record above the cursor, so a later chunk of the same run examines
        it; excluding it saves a model call whose likeliest outcome is the refusal
        above. Whether a *second-order* consolidation is wanted at all is a quality
        question ADR-0106 §12 files with leg 8's measurement (#809).

        Returns:
            What the run did, in counts and two dispositions.

        Raises:
            MemoryStoreError: As the store or the write path raises.
            ModelError: Propagated unwrapped from the provider, its classification
                intact (ADR-0013 §5).
            ValueError: If the injected clock's reading does not conform.
        """
        deadline = self._clock() + self._run_budget
        chunks = examined = proposed = committed = deferred = rejected = 0
        unusable = over_limit = self_cited = 0
        exhausted = halted = False
        # What this run has already proposed. A committed consolidation is a new
        # record above the cursor, so a later chunk of this same run would examine
        # it — and feeding a run its own output back is not merely wasteful, it
        # deterministically fails: the model generalises over two consolidations
        # into something the policy folds onto one of them, and the writer refuses
        # a write landing at an id the proposal cites, because the belief "would
        # stand as its own warrant" (ADR-0081 §1). That is a `MemoryStoreError` on
        # every run, identically, so the job stalls permanently rather than
        # spending a call and moving on. Excluding them costs nothing and lets the
        # cursor advance past them in the same run.
        produced: set[str] = set()
        while True:
            # At a chunk *boundary*, so no chunk is abandoned part-way: a run may
            # overrun its budget by at most one chunk's duration (ADR-0111 §4).
            if self._clock() >= deadline:
                break
            chunk = await self._memory.walk_records(self._walk, limit=self._chunk_size)
            if chunk.position is None:
                exhausted = True
                break
            examined += len(chunk.records)
            outcome = await self._consolidate(
                [record for record in chunk.records if record.id not in produced]
            )
            produced |= outcome.produced
            proposed += outcome.proposed
            committed += outcome.committed
            deferred += outcome.deferred
            rejected += outcome.rejected
            unusable += outcome.unusable
            over_limit += outcome.over_limit
            self_cited += outcome.self_cited
            if outcome.refused:
                halted = True
                break
            # Only now: everything above is durable, so the cursor lags its
            # effects rather than leading them.
            await self._memory.advance_walk(self._walk, position=chunk.position)
            chunks += 1
        return ConsolidationReport(
            chunks=chunks,
            examined=examined,
            proposed=proposed,
            committed=committed,
            deferred=deferred,
            rejected=rejected,
            discarded_unusable=unusable,
            discarded_over_limit=over_limit,
            refused_self_citing=self_cited,
            exhausted=exhausted,
            halted=halted,
        )

    async def _consolidate(self, records: Sequence[MemoryRecord]) -> _ChunkOutcome:
        """Turn one chunk into proposals and route each through the write stage."""
        if not records:
            # Nothing to consolidate and nothing to spend: an empty chunk is a
            # range that held nothing eligible, and sending an empty prompt would
            # spend an egress to be told nothing.
            return _ChunkOutcome()
        # Computed **here**, from the set this stage selected, before the model is
        # asked anything — so no value the producer emits can reach the field even
        # in principle (ADR-0106 §3). The disjunction is over
        # `rests_on_recorded_external_content` rather than over the band, because
        # a `DERIVED` input carrying the marker is tainted too and a band-only test
        # is fail-open against exactly the second-order consolidation ADR-0106 §4's
        # monotonicity exists to stop.
        tainted = any(rests_on_recorded_external_content(record.provenance) for record in records)
        now = self._clock()
        labels = {f"R{index + 1}": record.id for index, record in enumerate(records)}
        confirmed = {
            record.id: record.provenance.last_confirmed_at
            for record in records
            if record.provenance.last_confirmed_at is not None
        }
        conversation = [
            Message(role=Role.SYSTEM, content=_SYSTEM_PROMPT),
            Message(role=Role.USER, content=_render(records)),
        ]
        reply = await self._model.complete(conversation)
        proposals, unusable, over_limit = self._distil(reply.content, labels, confirmed, now)
        return await self._route(
            proposals, tainted=tainted, unusable=unusable, over_limit=over_limit
        )

    async def _route(
        self,
        proposals: Sequence[MemoryUpdateProposal],
        *,
        tainted: bool,
        unusable: int,
        over_limit: int,
    ) -> _ChunkOutcome:
        """Mark each proposal and put it through the write stage, counting rulings."""
        outcome = _ChunkOutcome(
            proposed=len(proposals),
            unusable=unusable,
            over_limit=over_limit,
            # Every proposal this stage made, whatever became of it — not only the
            # ids that committed. A deferred one lands under its own id when the
            # user answers yes (ADR-0078 §5's re-ingest), so a run that excluded
            # only what committed would still meet its own work coming back.
            produced=frozenset(proposal.proposed.id for proposal in proposals),
        )
        for proposal in proposals:
            try:
                written = await self._writes.write(self._marked(proposal, tainted=tainted))
            except FoldOntoCitedRecordError:
                # The generalisation landed on one of the records it cites, and the
                # policy — not this stage — chose that destination (ADR-0116 §2).
                # A normal outcome of generalising, so it is a ruling on **one
                # proposal**: counted, carried on from, and the chunk still recorded
                # as done (§4, §5). Nothing is re-proposed and nothing is repaired:
                # dropping the offending citation or re-asking the model over the
                # same inputs is forbidden by §4's third clause.
                #
                # `SelfConsumingWriteError` is deliberately **not** caught. It is
                # the arm where this stage minted the id *and* cited it — a bug in
                # this producer — and §4's second clause has it propagate, so the
                # run ends with the chunk unrecorded and ADR-0111 §5's halt applies
                # like any other fault. Catching the base to reach both would
                # absorb that bug into the path built for the case that is not one.
                outcome = outcome.with_self_cited()
                continue
            kind = written.result.decision.kind
            admission = written.admission
            if kind is MemoryDecisionKind.REJECT:
                outcome = outcome.with_rejected()
            elif kind is MemoryDecisionKind.ASK_USER:
                if admission is not None and admission.outcome is DeferralAdmissionOutcome.REFUSED:
                    # The queue is at its cap. The proposal has not been disposed
                    # of, so the run halts and the chunk stays unrecorded: its
                    # material is retained and re-proposed on a later run rather
                    # than consumed (ADR-0106 §6, ADR-0111 §5).
                    return outcome.with_refused()
                outcome = outcome.with_deferred()
            else:
                outcome = outcome.with_committed()
        return outcome

    def _marked(self, proposal: MemoryUpdateProposal, *, tainted: bool) -> MemoryUpdateProposal:
        """Stamp the computed taint marker on ``proposal``, discarding the producer's.

        **Assignment, never a disjunction with what the producer emitted**, which
        is ADR-0106 §3's "discarded, not merged" — and the difference is the whole
        guarantee. A merge would make forgetting harmless in one direction and
        fatal in the other; assignment leaves no code path in which the producer's
        value has an effect, so the marker is a fact the caller computed rather
        than a claim the model made. ADR-0094 §5's "a claim carried in a submission
        is not evidence of the standing it claims" with the sign flipped, and
        flipping the sign does not restore the guarantee.
        """
        provenance = proposal.proposed.provenance.model_copy(
            update={"derived_from_external": tainted}
        )
        return proposal.model_copy(
            update={"proposed": proposal.proposed.model_copy(update={"provenance": provenance})}
        )

    def _distil(
        self,
        content: str,
        labels: dict[str, str],
        confirmed: dict[str, datetime],
        now: datetime,
    ) -> tuple[tuple[MemoryUpdateProposal, ...], int, int]:
        """Turn one reply into proposals and the two counts of what was thrown away.

        Validates every entry first and applies the cap to the survivors, in that
        order and for ADR-0077 §4's reason: capping first would let a malformed
        entry occupy a slot a good one could have filled, and would file the same
        bad entry under two different counts depending on where it happened to sit.
        """
        entries = _entries(content)
        if entries is None:
            # An envelope that does not decode, or that carries no `beliefs` list,
            # is one entry and that entry is unusable. Without the synthetic unit,
            # "I cannot help" yields zero proposals and zero discards, which is
            # indistinguishable from a model that read the chunk and honestly
            # proposed nothing.
            return (), 1, 0
        usable: list[MemoryUpdateProposal] = []
        unusable = 0
        for entry in entries:
            proposal = self._to_proposal(entry, labels, confirmed, now)
            if proposal is None:
                unusable += 1
            else:
                usable.append(proposal)
        # Both counts, because dropping a *usable* belief on the cap is data loss
        # and a report that showed neither would make a capped reply look like a
        # model that proposed exactly the cap.
        return (
            tuple(usable[: self._max_proposals]),
            unusable,
            max(len(usable) - self._max_proposals, 0),
        )

    def _to_proposal(
        self,
        entry: object,
        labels: dict[str, str],
        confirmed: dict[str, datetime],
        now: datetime,
    ) -> MemoryUpdateProposal | None:
        """Build one proposal, or ``None`` where the entry cannot be used.

        Every refusal is counted and none is repaired: an unmappable citation is
        dropped rather than replaced, and a belief left citing too little is
        discarded rather than propped up with the chunk wholesale. Evidence
        attached to satisfy a rule is not evidence (ADR-0077 §5).
        """
        shape = _shape_of(entry)
        if shape is None:
            return None
        kind, step, text, fields = shape
        cited = _resolve(fields.get("evidence"), labels)
        if len(cited) < _EVIDENCE_FLOOR[step]:
            return None
        provenance = Provenance(
            source=step,
            confidence=_confidence(step, len(cited)),
            evidence=cited,
            last_updated=now,
            # The latest confirming instant among the warrants this belief cites,
            # never the moment of derivation — `now` is transaction time and is
            # already above. Taken over the ids *this stage* resolved the citations
            # to, so a value the model emitted could not reach it. ADR-0106 §8
            # rules nothing about either confidence quantity and leaves both to
            # ADR-0103's lane; this is the honest reading available today, and a
            # consolidation confirmed no later than any warrant it rests on is the
            # conservative direction.
            last_confirmed_at=max(
                (confirmed[cid] for cid in cited if cid in confirmed), default=None
            ),
            # Deliberately **not** set from the entry. The producer is given no way
            # to speak about taint at all — the prompt forbids "any claim about
            # where the material came from" — and `_marked` overwrites the field
            # unconditionally on the way to the gate, so both halves of ADR-0106
            # §3 hold: the value is the selector's, and the producer's is discarded.
        )
        rationale = fields.get("rationale")
        try:
            record = _record(kind, text, fields.get("steps"), provenance, self._id_factory())
            return MemoryUpdateProposal(
                proposed=record,
                rationale=(
                    rationale.strip()
                    if isinstance(rationale, str) and rationale.strip()
                    else _DEFAULT_RATIONALE
                ),
            )
        except ValidationError:
            # A `core` invariant the entry's own text broke. Counted like any other
            # unusable entry rather than raised: one bad belief does not fail a run.
            return None


@dataclass(frozen=True, slots=True)
class _ChunkOutcome:
    """What one chunk's proposals came to, before the run folds them in."""

    proposed: int = 0
    committed: int = 0
    deferred: int = 0
    rejected: int = 0
    unusable: int = 0
    over_limit: int = 0
    self_cited: int = 0
    refused: bool = False
    produced: frozenset[str] = frozenset()

    def with_committed(self) -> _ChunkOutcome:
        """One more committing ruling."""
        return replace(self, committed=self.committed + 1)

    def with_deferred(self) -> _ChunkOutcome:
        """One more question the queue admitted."""
        return replace(self, deferred=self.deferred + 1)

    def with_rejected(self) -> _ChunkOutcome:
        """One more proposal the gate refused outright."""
        return replace(self, rejected=self.rejected + 1)

    def with_self_cited(self) -> _ChunkOutcome:
        """One more proposal the write path refused for folding onto a citation."""
        return replace(self, self_cited=self.self_cited + 1)

    def with_refused(self) -> _ChunkOutcome:
        """The queue refused a question, so the run halts and the chunk stays open."""
        return replace(self, refused=True)


def _render(records: Sequence[MemoryRecord]) -> str:
    """Render the chunk as labelled entries the model cites by label.

    Content is truncated to :data:`_CONTENT_BUDGET` characters per record: a chunk
    is fifty records by default and every one of them is Tier 1 material leaving
    the process, so the batch is bounded in bytes as well as in count. Ingested
    text is data and never instruction (ADR-0098 §1); the labels are ours and the
    model is told to cite them, so nothing a record's own content says can name a
    record the model was not shown.
    """
    lines = []
    for index, record in enumerate(records):
        body = record.content[:_CONTENT_BUDGET]
        lines.append(f"[R{index + 1}] ({record.kind}) {body}")
    return "\n".join(lines)


def _shape_of(entry: object) -> tuple[str, MemorySource, str, dict[str, object]] | None:
    """Read one entry's kind, epistemic step and text, or ``None`` if unusable.

    Split out from :meth:`ConsolidationStage._to_proposal` so that method stays
    inside the complexity bound: the shape checks and the construction fail for
    entirely different reasons — a malformed *entry* versus a `core` invariant the
    entry's own text broke — and both are counted the same way regardless.
    """
    if not isinstance(entry, dict):
        return None
    kind = entry.get("kind")
    step = _step_of(entry.get("step"))
    text = entry.get("content")
    if kind not in _PROPOSABLE_KINDS or step is None:
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    return str(kind), step, text.strip(), entry


def _step_of(raw: object) -> MemorySource | None:
    """Map the entry's epistemic step onto the two bands a consolidation may take.

    ``ATTESTED`` and ``USER_ASSERTED`` are unreachable by construction rather than
    refused downstream: a consolidation is this system's generalisation over
    records, so claiming a source reported it would be false, and
    ``_attested_iff_attestation`` would demand an ``Attestation`` a fold over many
    records cannot honestly fill (ADR-0106 §5).
    """
    match raw:
        case "observed":
            return MemorySource.OBSERVED
        case "inferred":
            return MemorySource.INFERRED
        case _:
            return None


def _resolve(raw: object, labels: dict[str, str]) -> tuple[str, ...]:
    """Map cited labels back onto the ids of the records actually read.

    A label the batch does not carry is dropped rather than repaired: the citation
    is ours to determine, and a model that can write an id can write one for a
    record it never saw (ADR-0047 §2). Duplicates collapse, so citing one record
    three times is one support rather than three — which matters because the
    confidence ladder counts *distinct* supports.
    """
    if not isinstance(raw, list):
        return ()
    resolved = [labels[label] for label in raw if isinstance(label, str) and label in labels]
    return tuple(dict.fromkeys(resolved))


def _record(
    kind: str, content: str, raw_steps: object, provenance: Provenance, record_id: str
) -> MemoryRecord:
    """Build the typed record the entry names.

    ``episodic`` is unreachable: :data:`_PROPOSABLE_KINDS` refuses it before this
    is called, which is why there are three arms and no fourth.
    """
    match kind:
        case "preference":
            return PreferenceMemory(
                id=record_id, content=content, provenance=provenance, preference=content
            )
        case "procedural":
            steps = (
                tuple(step.strip() for step in raw_steps if isinstance(step, str) and step.strip())
                if isinstance(raw_steps, list)
                else ()
            )
            return ProceduralMemory(
                id=record_id, content=content, provenance=provenance, situation=content, steps=steps
            )
        case _:
            return SemanticMemory(
                id=record_id, content=content, provenance=provenance, fact=content
            )


def _entries(content: str) -> list[object] | None:
    """Pull the ``beliefs`` list out of a reply, or ``None`` if there is none."""
    payload = _extract_object(content)
    if payload is None:
        return None
    beliefs = payload.get("beliefs")
    if not isinstance(beliefs, list):
        return None
    return list(beliefs)


def _extract_object(content: str) -> dict[str, object] | None:
    """Decode the first JSON object in ``content``, tolerating surrounding prose.

    Bounded by :data:`_MAX_EXTRACTION_MISSES` failed attempts, so a brace-dense
    reply cannot make this quadratic on the event loop.
    """
    decoder = json.JSONDecoder()
    misses = 0
    for index, character in enumerate(content):
        if character != "{":
            continue
        try:
            decoded, _ = decoder.raw_decode(content, index)
        except ValueError:
            misses += 1
            if misses >= _MAX_EXTRACTION_MISSES:
                return None
            continue
        if isinstance(decoded, dict):
            return decoded
    return None
