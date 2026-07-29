"""The observation stage: select episodes, observe them, ingest what comes back.

ADR-0077 §8's explicit operation, in one object. The producer holds no store and
no writer — episodes in, proposals out (ADR-0077 §1) — so **selection** and the
**write path** belong here, in `orchestration`, the one layer that legitimately
holds both durable stores by injection (ADR-0074 §9). This stage:

* **selects** a bounded batch — a named conversation's most recent turns, or the
  same window over the most recently active conversation (§8);
* **hands** the resolved :class:`~ai_assistant.core.types.EpisodicMemory` values
  to the injected :class:`~ai_assistant.core.protocols.Observer`;
* **ingests** each returned proposal through
  :meth:`~ai_assistant.core.protocols.MemoryWriter.ingest`, in order and
  independently, ruling by ruling (§4) — the model proposes, a deterministic
  policy disposes, and this stage rules on nothing;
* **reports** what happened, including the route that read the episodes (§3) and
  every deferral the gate would otherwise drop silently (§4).

There is no polling, no background task and no per-turn trigger: nothing waits on
an observation while a turn does, and leg 5's scheduler becomes a second caller of
the same operation with no contract change (§8). There is no durable cursor
either — a repeat folds into a ``REINFORCE`` and the producer's confidence is
deterministic on its inputs, so a fold that takes the maximum finds nothing higher
(§8).

Nothing concrete is imported: every collaborator arrives by injection and is seen
only through its Protocol (CLAUDE.md golden rule 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_assistant.core.errors import UnresolvedEvidenceError
from ai_assistant.core.types import EpisodicMemory, MemoryKind
from ai_assistant.orchestration.engine import LearnDecision, learn_decision

if TYPE_CHECKING:
    from ai_assistant.core.protocols import (
        ConversationStore,
        MemoryStore,
        MemoryWriter,
        Observer,
    )
    from ai_assistant.core.types import (
        MemoryIngestResult,
        MemorySource,
        MemoryUpdateProposal,
    )

#: What :attr:`ObservedProposal.reason` says for a proposal the write path refused
#: because the evidence it cited no longer resolves (ADR-0077 §5). The stage's own
#: words, not a policy's: no ruling was sought, so there is no policy reason to
#: relay, and an empty string would render as a decision nobody made.
_UNSUPPORTED_REASON = (
    "the evidence it cited went away between selection and the write, so nothing was stored"
)


def _check_batch_size(value: int) -> None:
    """Refuse a batch bound the stage could only honour by observing nothing.

    ``Settings`` already refuses both out-of-range values at load, so this guards
    the *constructor* — the seam a test or a second composition root reaches
    directly — for ADR-0022 §4a's reason: tuning that disables the work while the
    caller keeps reporting health is validated where it is supplied, not where its
    effect is eventually noticed.

    Raises:
        TypeError: If ``value`` is not an integer. ``bool`` is excluded — it is an
            ``int`` subclass and a flag is not a count — and a ``float`` is refused
            rather than compared, since a non-integral limit reaches
            ``ConversationStore.turns`` and fails far from the mistake.
        ValueError: If it is not positive, or is at or above ``2**63``, which is
            the range ``ConversationStore.turns`` refuses outside of.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"batch_size must be an integer, got {value!r}"
        raise TypeError(msg)
    if not 1 <= value < 2**63:
        msg = f"batch_size must be at least 1 and below 2**63, got {value}"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ObservedProposal:
    """One belief the observer proposed, and what the write path did with it.

    A frozen ``orchestration`` dataclass beside
    :class:`~ai_assistant.orchestration.engine.IngestSummary` and for its reason:
    it crosses no *subsystem* boundary, only `interfaces`, which already depends on
    this package (ADR-0042 §1).

    **It pairs the proposal with its ruling, and that pairing is the decision**
    (ADR-0077 §9.7). A :class:`~ai_assistant.core.types.MemoryIngestResult` carries
    a ruling and a record id and nothing else, and for an ``ASK_USER`` that id is
    ``None`` — so an entry built from the result alone would render a deferral as a
    bare ruling with nothing to show, which is precisely the visibility ADR-0077 §4
    promises while ADR-0078 is unbuilt. Carrying the candidate's own content, its
    citation count and the policy's reason is what makes a deferral actionable with
    the surfaces leg 1 already shipped.

    Attributes:
        content: The canonical text rendering of the belief that was proposed.
        kind: Which typed memory it is. Never ``EPISODIC``: an observer distils
            evidence, it does not manufacture it (ADR-0077 §2).
        step: The epistemic step the producer took — ``OBSERVED`` where the cited
            evidence entails the belief, ``INFERRED`` where it merely supports it
            (ADR-0072 §3). Both land in the ``DERIVED`` band, so the band carries
            no information here and the *step* is the informative half.
        confidence: How strongly the producer proposed holding it, always strictly
            below 1.0 — the standing only the user's own word carries.
        evidence_count: How many episodes it cites. At least one, and at least two
            distinct ones for an ``INFERRED`` belief (ADR-0077 §5).
        rationale: The producer's own statement of why the batch justifies it.
        decision: How memory folded it, or ``None`` when **no ruling was ever
            sought** — the write path refused it because the evidence it cited no
            longer resolves (ADR-0077 §5). ``None`` is not a sixth ruling: a
            refusal is not a decision, and fabricating one would put a ruling
            nobody made into the report.
        record_id: The id of the record left live by the write, or ``None`` when
            nothing was stored. This is the id ``assistant beliefs`` lists and
            ``assistant forget`` takes, so an observed belief is immediately
            inspectable.
        reason: The policy's own justification for the ruling — or, where
            ``decision`` is ``None``, this stage's statement of why the proposal
            was dropped before any policy saw it.
    """

    content: str
    kind: MemoryKind
    step: MemorySource
    confidence: float
    evidence_count: int
    rationale: str
    decision: LearnDecision | None
    record_id: str | None
    reason: str

    @property
    def stored(self) -> bool:
        """Whether the write left a record live in memory."""
        return self.record_id is not None

    @classmethod
    def ruled(cls, proposal: MemoryUpdateProposal, result: MemoryIngestResult) -> ObservedProposal:
        """Pair a proposal with the ruling the write path returned for it."""
        return cls._project(
            proposal,
            decision=learn_decision(result.decision.kind),
            record_id=result.record_id,
            reason=result.decision.reason,
        )

    @classmethod
    def unsupported(cls, proposal: MemoryUpdateProposal) -> ObservedProposal:
        """Record a proposal the write path refused for unresolved evidence.

        Reported rather than dropped in silence: a belief whose support went away
        under the observation is not stored, and saying so is the difference
        between an outcome the user can read and a count that went missing
        (ADR-0077 §5).
        """
        return cls._project(proposal, decision=None, record_id=None, reason=_UNSUPPORTED_REASON)

    @classmethod
    def _project(
        cls,
        proposal: MemoryUpdateProposal,
        *,
        decision: LearnDecision | None,
        record_id: str | None,
        reason: str,
    ) -> ObservedProposal:
        """Read the candidate half of a proposal, and pair it with an outcome.

        The one place a ``core``
        :class:`~ai_assistant.core.types.MemoryUpdateProposal` is read on the
        observation path, exactly as
        :meth:`~ai_assistant.orchestration.engine.LearnOutcome.from_results` holds
        that boundary on the learn path (ADR-0042 §1). Both entry points go through
        it, so a dropped proposal is rendered as fully as a ruled one.
        """
        record = proposal.proposed
        provenance = record.provenance
        return cls(
            content=record.content,
            kind=MemoryKind(record.kind),
            step=provenance.source,
            confidence=provenance.confidence,
            evidence_count=len(provenance.evidence),
            rationale=proposal.rationale,
            decision=decision,
            record_id=record_id,
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class ObservationReport:
    """What one observation pass did (ADR-0077 §9.7).

    An ``orchestration`` type beside
    :class:`~ai_assistant.orchestration.engine.LearnOutcome`, **not** a ``core``
    one: it crosses no subsystem boundary, only `interfaces` (ADR-0022 §2's
    reasoning for ``TurnResult``). It is deliberately not named ``…Outcome``,
    because it *relays* counts from ``core``'s
    :class:`~ai_assistant.core.types.ObservationOutcome` and two near-identical
    names for a producer's result and a stage's report would invite reading one
    invariant onto the other.

    **The counts are kept apart on purpose.** ``ObservationOutcome``'s two are
    exhaustive over the entries the *model* emitted, so a proposal the producer
    legitimately made and the writer then refused is a different fact: folding it
    into either would make that invariant a lie (ADR-0077 §5, §9.7). It gets a
    count of its own.

    Attributes:
        proposals: One entry per proposal the observer returned, in the producer's
            order, each paired with its ruling — or with the unresolved-evidence
            drop that replaced it. Empty is a normal outcome, not an error.
        discarded_unusable: Relayed **unchanged** from the producer: entries it
            refused for a reason of its own — unparseable, failing validation,
            citing evidence it was never handed, below its evidence floor, or
            naming a kind an observer may not propose.
        discarded_over_limit: Relayed unchanged: otherwise-usable proposals the
            producer dropped to meet its configured maximum.
        dropped_unsupported: This stage's own count of proposals the **write path**
            refused because every episode they cited had stopped resolving between
            selection and the write. An ordinary consequence of a finite retention
            horizon, never a producer fault — a fault propagates instead.
        route: The model route that read the episodes, **absent when none did**. A
            window whose turns have all lost their episodes selects an empty batch
            and the observer is not called at all, so naming a route would claim a
            read that never happened — the one thing ADR-0013 §6's reporting exists
            to make truthful.
        conversation_id: The conversation whose turns were read, or ``None`` when
            the store held none to read. Carried because the operation *selects*
            when it is given no id — "the most recently active" — and a report that
            did not say which conversation was read would leave the user unable to
            tell what the model was shown.
        episodes_read: How many episodes the batch held. At most the configured
            batch size, and **short** where a turn's episode no longer resolves:
            such a turn is skipped and the batch is not backfilled, so the window's
            span stays a fixed number of recent turns (ADR-0074 §5, ADR-0077 §8).
    """

    proposals: tuple[ObservedProposal, ...] = ()
    discarded_unusable: int = 0
    discarded_over_limit: int = 0
    dropped_unsupported: int = 0
    route: str | None = None
    conversation_id: str | None = None
    episodes_read: int = 0

    @property
    def stored(self) -> int:
        """How many proposals left a record live in memory."""
        return sum(1 for proposal in self.proposals if proposal.stored)

    @property
    def discarded(self) -> int:
        """How much was thrown away in total, by the producer and by the write path."""
        return self.discarded_unusable + self.discarded_over_limit + self.dropped_unsupported


class ObservationStage:
    """Selects a batch of episodes, observes it, and ingests what comes back."""

    def __init__(  # noqa: PLR0913 — four injected collaborators plus the bound and the route label
        self,
        *,
        observer: Observer,
        conversations: ConversationStore,
        memory: MemoryStore,
        writer: MemoryWriter,
        batch_size: int,
        route: str,
    ) -> None:
        """Wire the stage from injected contracts.

        Three obligations no type can express, so each is the composition root's
        (ADR-0028 §4's shape, applied three times):

        * **``memory`` must be the store ``writer`` persists to**, and the store
          ``conversations`` names episodes in. Wired to a second store, the batch
          would be selected from records the write path cannot cite and every
          proposal would be refused for unresolved evidence.
        * **``batch_size`` must not exceed the observer's own maximum.** ADR-0077
          §1 puts the refusal on the producer because the Protocol is a
          cross-subsystem contract and a stage that bounds its own selection is not
          evidence that the *next* caller will; §9.7 correspondingly has this stage
          select **at most** that many, so the producer's ``ValueError`` guards a
          contract rather than a routine path. Both values come from one
          ``Settings`` field, which is what keeps them in step.
        * **``route`` must name the route the injected ``observer`` actually reads
          through.** No seam exposes it — an ``Observer`` holds its provider and
          shows nobody — and reporting which model read the episodes is precisely
          what ADR-0077 §3 asks this operation for, so the label is supplied by the
          layer that built the provider. A stage handed a label that does not match
          would report a read that did not happen, which is worse than reporting
          none.

        Args:
            observer: The producer. It is handed episodes and returns proposals; it
                holds no store, no writer and no policy, so it can neither widen
                its own batch nor rule on its own output (ADR-0077 §1, §4).
            conversations: The durable conversation index, read for the selection —
                the most recently active conversation, and a conversation's most
                recent turns.
            memory: Long-term memory, read to resolve each turn's episode. The same
                store ``writer`` persists to.
            writer: The memory write path — conflicts, the policy's ruling and the
                write in one call. It holds the policy; this stage does not, and
                must not: "the model proposes, a deterministic policy disposes" is
                only true while the component selecting the batch cannot also rule
                on what comes back (ADR-0005 §3, ADR-0075 §2).
            batch_size: How many of a conversation's most recent turns one pass
                reads. A **maximum, not a quota**: a window containing a turn whose
                episode no longer resolves yields a shorter batch rather than
                reaching further back (ADR-0077 §8).
            route: The ``"provider:model"`` spec the observer reads through,
                reported on every pass that actually called it (ADR-0013 §6).

        Raises:
            TypeError: If ``batch_size`` is not an integer.
            ValueError: If ``batch_size`` is outside ``[1, 2**63)``.
        """
        _check_batch_size(batch_size)
        self._observer = observer
        self._conversations = conversations
        self._memory = memory
        self._writer = writer
        self._batch_size = batch_size
        self._route = route

    async def observe(self, conversation_id: str | None = None) -> ObservationReport:
        """Observe one conversation's recent turns and ingest what they justify.

        The whole operation, in the order ADR-0077 §8 names: select, observe,
        ingest, report.

        **Selection is conversation-scoped, and that is the ratified rule rather
        than an implementation detail.** An id observes that conversation's most
        recent ``batch_size`` turns; no id observes the same window over the **most
        recently active** conversation. "The newest N episodes in the store" was
        rejected explicitly: it would re-read the same N on every run, and the
        N+1th could never be requested at all — it would expire unobserved with no
        way for the user to reach it. With a conversation as the unit, everything
        is reachable, because ``assistant conversations`` lists them and the user
        can name any one.

        **A turn whose episode does not resolve is skipped, and the batch is not
        backfilled** (ADR-0074 §5's rule, applied unchanged). Backfilling would make
        the window's *span* depend on how many gaps it contains, so two runs over
        one conversation would read different stretches of it.

        **An empty batch reaches no observer.** There is nothing to observe, no
        provider is called, and the report names no route (§9.7).

        **Each proposal is ingested in order and independently**, exactly as the
        feedback leg already does. There is no transaction — ``MemoryStore`` offers
        none — so a writer failure propagates with the earlier proposals *already
        applied*, and nothing reports success for a partially applied set: that
        would be a claim about memory integrity this stage cannot make (ADR-0022
        §4). ``assistant beliefs`` shows exactly what landed and ``forget`` removes
        any of it.

        **Unresolved evidence is a race or a bug, and only this stage can tell
        them apart.** The writer sees "this id does not resolve" and cannot say
        whether the record expired under a finite horizon or was never handed to
        the producer at all. So it raises, carrying the ids, and this stage compares
        them against the batch it selected: **every** unresolved id inside the batch
        is the race — drop that proposal, count it, and carry on ingesting the rest
        — while **any** id outside it is the producer citing something it was never
        given, and propagates. The quantifier is "every", deliberately: a fault
        accompanied by an expiry is still a fault, and swallowing the pair would
        bury a producer bug under the race that happened to accompany it.

        Args:
            conversation_id: The conversation to observe, or ``None`` for the most
                recently active one. Untrusted input from an adapter, relayed to the
                store, which refuses an id it does not know rather than inventing a
                conversation for it.

        Returns:
            What was proposed, what became of each proposal, what was thrown away,
            and which route read the episodes.

        Raises:
            UnknownConversationError: If ``conversation_id`` names nothing, or names
                a conversation the user deleted.
            ConversationStoreError: If the conversation index cannot be read.
            MemoryStoreError: If an episode cannot be read, or the write path
                failed. :class:`~ai_assistant.core.errors.UnresolvedEvidenceError`
                — a subclass — reaches a caller only for a citation the batch never
                contained, which is a producer fault rather than an expiry.
            ModelError: Propagated unwrapped from the observer's provider, its
                classification intact (ADR-0013 §5). The user asked for observation
                and it did not happen; returning "no beliefs" would be
                indistinguishable from "nothing to learn" (ADR-0022 §3). The route
                never falls back, so the failure ends the pass (ADR-0077 §3).
            ValueError: If the producer refuses the batch — larger than its
                configured maximum, or carrying one episode twice. Both are wiring
                faults rather than user input: this stage selects at most
                ``batch_size`` distinct turns, so neither is reachable from a
                composition root that gave the two bounds one value.
        """
        target = await self._target(conversation_id)
        if target is None:
            return ObservationReport()
        episodes = await self._select(target)
        if not episodes:
            return ObservationReport(conversation_id=target)
        outcome = await self._observer.observe(episodes)
        selected = frozenset(episode.id for episode in episodes)
        proposals: list[ObservedProposal] = []
        dropped = 0
        for proposal in outcome.proposals:
            entry = await self._ingest(proposal, selected=selected)
            if entry.decision is None:
                dropped += 1
            proposals.append(entry)
        return ObservationReport(
            proposals=tuple(proposals),
            discarded_unusable=outcome.discarded_unusable,
            discarded_over_limit=outcome.discarded_over_limit,
            dropped_unsupported=dropped,
            route=self._route,
            conversation_id=target,
            episodes_read=len(episodes),
        )

    async def _target(self, conversation_id: str | None) -> str | None:
        """The conversation this pass reads, or ``None`` when there is none.

        An id is taken as given — whether it names a conversation is the store's
        question, and it refuses one it does not know. Without an id the selector
        is ``recent``'s first row, which ADR-0074 §2 already made a **total** order
        (``last_active_at`` descending, ``id`` ascending as the tie-break), so two
        implementations cannot disagree about which conversation is "the most
        recently active" one.
        """
        if conversation_id is not None:
            return conversation_id
        recent = await self._conversations.recent(limit=1)
        return recent[0].id if recent else None

    async def _select(self, conversation_id: str) -> tuple[EpisodicMemory, ...]:
        """Resolve the conversation's most recent turns into a batch of episodes.

        The store's read-time axes do the filtering for free: ``get`` never returns
        an expired or non-live record and a deleted conversation's episodes are
        destroyed, so an episode the user has put beyond reach is beyond the
        observer's reach too, with no second filter to keep in step (ADR-0077 §1).

        A record that resolves but is not an episode is skipped like an id that does
        not resolve at all. The ``conv:`` namespace is reserved to captured
        conversation turns, so this is unreachable in practice; it is written
        because the alternative — handing a non-episode to a seam typed for
        episodes — would be a contract breach discovered inside the producer.
        """
        turns = await self._conversations.turns(conversation_id, limit=self._batch_size)
        episodes: list[EpisodicMemory] = []
        for turn in turns:
            record = await self._memory.get(turn.episode_id)
            if isinstance(record, EpisodicMemory):
                episodes.append(record)
        return tuple(episodes)

    async def _ingest(
        self, proposal: MemoryUpdateProposal, *, selected: frozenset[str]
    ) -> ObservedProposal:
        """Put one proposal through the write path, discriminating race from bug.

        Raises:
            UnresolvedEvidenceError: If any unresolved id was **not** in the batch
                this pass selected — the producer cited something it was never
                handed. An error carrying no ids at all propagates too: nothing
                identifies it as the race, and an implementation reading the empty
                quantifier as "every id was in the batch" would swallow exactly the
                fault this discrimination exists to surface.
            MemoryStoreError: As the writer raises.
        """
        try:
            result = await self._writer.ingest(proposal)
        except UnresolvedEvidenceError as exc:
            unresolved = frozenset(exc.unresolved_ids)
            if not unresolved or not unresolved <= selected:
                raise
            return ObservedProposal.unsupported(proposal)
        return ObservedProposal.ruled(proposal, result)


__all__ = [
    "ObservationReport",
    "ObservationStage",
    "ObservedProposal",
]
