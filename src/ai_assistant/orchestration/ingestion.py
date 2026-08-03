"""The ingestion stage: read one source, and propose what it read (ADR-0093 §6).

ADR-0093 §1's ruling, in one object: "Selecting when a reader runs, and ingesting
what it returns, are ``orchestration``'s. A reader is never its own caller." The
producer holds no store and no writer — a source in, proposals out — so the
**write path** belongs here, in `orchestration`, the one layer that legitimately
holds the durable stores by injection (ADR-0074 §9). This stage:

* **reads** the injected :class:`~ai_assistant.core.protocols.Reader` once,
  within that reader's own bound (§5 — the bound is the reader's configuration,
  which is why :meth:`~ai_assistant.core.protocols.Reader.read` takes no
  arguments and this stage passes none);
* **ingests** each returned proposal through the orchestration write stage, in
  order and independently — the reader proposes, a deterministic
  :class:`~ai_assistant.core.protocols.MemoryPolicy` disposes, and this stage
  rules on nothing (§1);
* **reports** what the source said and what became of it.

**Every belief a reading proposes reaches memory through the gate**, and that is
the reason this operation exists at all. ADR-0075 §2 named this wave in its
exclusion list and reserved the capture exemption's argument rather than granting
it; ADR-0093 §1 declines to make it. A calendar entry is a third party's report —
the definition of the ``ATTESTED`` band — and a band whose whole standing is that
someone else said it is the last band that should reach the store unmediated.

**Nothing here is wired into a turn** (§6). Ingestion has a model-free but
unbounded-in-consequence tail — a policy ruling, a write, possibly a parked
question — and nobody is waiting for any of it, which is ADR-0077 §8's first
reason applied unchanged: "Nothing is waiting on it, and a turn is." The facet
read §3 permits at assembly time is a different path with a different cadence,
and it proposes nothing; it is not this stage's and does not exist yet (§7a
reserves it until ``CurrentContext`` grows the field).

**No check stands between the reader and the writer, deliberately.** The sibling
:class:`~ai_assistant.orchestration.observation.ObservationStage` refuses a
proposal citing an episode it never handed the producer, because only that stage
knows the batch and the writer cannot see it. Nothing here is knowable only to
this layer: §4's band and episode rules are producer-side obligations that the
shared ``Reader`` conformance suite pins on **every** implementation, so
re-asserting them here would be a second copy of a rule the seam already holds,
sited where a reader's non-conformance would be reported as an ingestion fault
rather than as the contract breach it is.

Nothing concrete is imported: the reader arrives by injection and is seen only
through its Protocol (CLAUDE.md golden rule 1). ``lint-imports`` enforces that
literally — no subsystem, `orchestration` included, may import
``ai_assistant.readers`` — which is exactly the arrangement ADR-0095 §3 kept the
contract in `core` to make possible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_assistant.core.types import MemoryDecisionKind

if TYPE_CHECKING:
    from datetime import datetime

    from ai_assistant.core.protocols import Reader
    from ai_assistant.orchestration.writes import MemoryWriteStage


@dataclass(frozen=True, slots=True)
class IngestionReport:
    """What one reading proposed, and what memory did with it (ADR-0093 §6).

    A plain dataclass rather than a ``core`` DTO, exactly as
    :class:`~ai_assistant.orchestration.engine.PurgeReport` is and for the same
    reason: this is **maintenance surface on a concrete class in
    ``orchestration``** (ADR-0083 §8), not something that crosses a subsystem
    boundary, and its only caller is the scheduler that lives above the
    composition root. ADR-0085 §1 fixes the promoted ``AssistantEngine`` surface
    at fifteen methods and this is not one of them, so nothing here is owed to
    `core`.

    **The counts partition the proposals, and each one names a *ruling*.** A
    ruling either deferred, or left a record live, or did neither;
    :attr:`rejected` is the remainder rather than a fourth stored number, so the
    three can never disagree with :attr:`proposed` (ADR-0085 §6b's rule: derive
    what the fields already determine). What became of the *question* a deferral
    raised is a different fact and is not carried here — see :attr:`deferred`.

    **It carries no proposal content, and that is not an oversight.** The only
    caller is the hub's scheduler, which never logs a job's result precisely
    because it cannot know which results are safe to render (ADR-0004 §5). A
    report that carried a calendar entry's text would put Tier 1 data one
    ``_log.info`` away from an operational log.
    """

    #: The producing reader's declared identity — Tier 2, and never a path
    #: (ADR-0093 §7). Carried so a second reader's job is distinguishable from
    #: this one's the day there is one.
    source: str
    #: The instant the reader acquired its source's bytes, as the reading carried
    #: it. **Ours, not the source's**: a reading-wide instant the source declares
    #: is ``as_of`` and is a different fact (ADR-0073 §4), which this report has
    #: no consumer for.
    read_at: datetime
    #: How many proposals the reading carried. **Zero is a success** and means the
    #: source had nothing to propose within the bound; a read that could not
    #: complete raises and produces no report at all (ADR-0093 §8).
    proposed: int
    #: How many left a record live in memory — an ``ACCEPT``, a ``REINFORCE``, a
    #: ``SUPERSEDE`` or a ``STORE_TEMPORARY``.
    stored: int
    #: How many the policy **ruled** ``ASK_USER`` on. Nothing was written for
    #: these.
    #:
    #: **It counts rulings, and deliberately does not claim a question was
    #: queued.** Three of the write stage's outcomes deferred and enqueued
    #: nothing new: a ``DataTier.SECRET`` proposal is ruled on and never
    #: persisted, because ADR-0004 §3 is unconditional that Tier 0 content lives
    #: "never in a database" and a durable queue is a file (ADR-0078 §1); a queue
    #: at its cap answers ``REFUSED``; and an existing question the key still
    #: speaks for answers ``SUPPRESSED``. Saying "the question waits in the
    #: queue" would be false in all three, and the falsehood is the interesting
    #: kind — it reads as a promise that someone will eventually be asked.
    #:
    #: **A fourth count for "and a question really was parked" is deliberately
    #: not added.** It would be surface with no consumer, which is the rule
    #: ADR-0045 §1 and ADR-0028 §7 state and ADR-0092 §10 applies to its own
    #: candidate field: this report's only caller is the scheduler, which never
    #: reads a job's result at all (ADR-0004 §5). The distinction ADR-0078 §10
    #: item 9 obliges is owed to an *adapter* rendering a deferral to the user,
    #: and this path has neither. What is owed here is not over-claiming, which
    #: is what the wording above buys instead.
    deferred: int

    @property
    def rejected(self) -> int:
        """How many the policy refused, storing nothing and asking nothing."""
        return self.proposed - self.stored - self.deferred


class IngestionStage:
    """Reads one source and puts what it proposed through the write path."""

    def __init__(self, *, reader: Reader, writes: MemoryWriteStage) -> None:
        """Wire the stage from an injected reader and the shared write stage.

        Args:
            reader: The producer. It is given its own source and its own bound
                (ADR-0093 §1, §5), so this stage neither locates the source nor
                widens the read: a caller able to widen it is a caller able to
                defeat the bound, which is the property ADR-0077 §1 bought by
                putting the maximum on the producer.
            writes: The orchestration **write stage** — the memory write path
                (conflicts, the policy's ruling and the write in one call) plus
                the durable queue an ``ASK_USER`` ruling parks its question in
                (ADR-0078 §3). It holds the policy; this stage does not, and must
                not: "the model proposes, a deterministic policy disposes" is only
                true while the component producing the proposals cannot also rule
                on them (ADR-0005 §3, ADR-0075 §2). It is the *stage* rather than a
                ``MemoryWriter`` of this stage's own because a producer's stage
                holding the writer directly would silently lose the queue — the
                third producer honouring ADR-0078 §3's one obligation.

                It must be the stage whose writer persists to the ``MemoryStore``
                the façade's inspection surface reads, a composition-root
                obligation no type can express (ADR-0028 §4): wired to a second
                store, an ingested belief would be unreadable and unforgettable
                through the surfaces the user actually has.
        """
        self._reader = reader
        self._writes = writes

    async def ingest(self) -> IngestionReport:
        """Read the source once and ingest every proposal it returned.

        The whole operation, in ADR-0093 §6's order: read, then ingest, then
        report. There is no selection step and no cursor — §5's bound is a
        function of the clock, the reader's configuration and the source's own
        content, "and of nothing else", which is precisely what makes a periodic
        re-read honest without new durable state.

        **Each proposal is ingested in order and independently**, exactly as the
        learn leg and the observation stage do it. There is no transaction —
        ``MemoryStore`` offers none — so a writer failure propagates with the
        earlier proposals *already applied*, and nothing reports success for a
        partially applied set: that would be a claim about memory integrity this
        stage cannot make (ADR-0022 §4). ``assistant beliefs`` shows exactly what
        landed and ``forget`` removes any of it.

        **A re-read duplicates rather than destroys, and that is the ratified
        residual.** A reader mints its own id per record (ADR-0092 §6), so a
        re-proposed entry is folded by *similarity* at the gate and not by
        identity: a small edit folds, a rewrite may land as a second live record
        (#631). What ADR-0093 §5 relies on is the narrower guarantee — nothing the
        store holds is destroyed by a re-read — and both records stay enumerable
        with their bands, rank below an ``ASSERTED`` one, and are killable by the
        user (ADR-0073 §5).

        Returns:
            What the source proposed and what became of each proposal. An empty
            reading yields a report with every count at zero, which is a
            **successful** pass over a source that had nothing to say — never a
            failure signal (ADR-0093 §8).

        Raises:
            ReaderError: If the read could not complete because of its source —
                missing, unreadable, malformed, over a bound, or past the reader's
                own deadline. Propagated rather than absorbed: an empty reading
                would be indistinguishable from success, and a reader whose file
                was unreadable for a week would look healthy for a week (§8). The
                scheduler logs it with its class and retries at the next due
                instant (§6, ADR-0083 §7).
            MemoryStoreError: As the write path raises.
            DeferralStoreError: If a deferred question could not be parked. A
                reader's proposals reach nobody in the moment, so ADR-0078 §7
                promises this path nothing beyond reporting the failure to its own
                stage — which propagating does.
            CancelledError: Re-raised unchanged from a cancelled read. It is never
                converted into a ``ReaderError``, so a shutdown that is working
                correctly is not logged as a source fault (ADR-0093 §8).
        """
        reading = await self._reader.read()
        stored = 0
        deferred = 0
        for proposal in reading.proposals:
            outcome = await self._writes.write(proposal)
            if outcome.result.decision.kind is MemoryDecisionKind.ASK_USER:
                deferred += 1
            elif outcome.result.record_id is not None:
                stored += 1
        return IngestionReport(
            source=reading.source,
            read_at=reading.read_at,
            proposed=len(reading.proposals),
            stored=stored,
            deferred=deferred,
        )


__all__ = [
    "IngestionReport",
    "IngestionStage",
]
