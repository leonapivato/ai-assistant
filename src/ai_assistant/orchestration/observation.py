"""The observation stage: select episodes, observe them, ingest what comes back.

ADR-0077 §8's explicit operation, in one object. The producer holds no store and
no writer — episodes in, proposals out (ADR-0077 §1) — so **selection** and the
**write path** belong here, in `orchestration`, the one layer that legitimately
holds both durable stores by injection (ADR-0074 §9). This stage:

* **selects** a bounded batch — the turns above a conversation's durable
  observation watermark, ordinal ascending, from the conversation the caller named
  or the first candidate by least recent activity (ADR-0212 §3);
* **hands** the resolved :class:`~ai_assistant.core.types.EpisodicMemory` values
  to the injected :class:`~ai_assistant.core.protocols.Observer`;
* **marks** each returned proposal with ADR-0204 §5's derivation value — the
  disjunction of ``supplied_withheld_content`` over the episodes it supplied,
  assigned rather than merged, exactly as ADR-0106 §3 has the consolidation stage
  mark its sibling field;
* **ingests** each returned proposal through
  :meth:`~ai_assistant.core.protocols.MemoryWriter.ingest`, in order and
  independently, ruling by ruling (§4) — the model proposes, a deterministic
  policy disposes, and this stage rules on nothing;
* **reports** what happened, including the route that read the episodes (§3) and
  every deferral the gate would otherwise drop silently (§4).

There is no polling, no background task and no per-turn trigger: nothing waits on
an observation while a turn does, and leg 5's scheduler becomes a second caller of
the same operation with no contract change (§8).

**There is a durable cursor, and it is a position rather than a certificate**
(ADR-0212 §1). The ``ConversationStore`` holds one watermark per conversation, this
stage is its only consumer, and a pass reads the turns above it and then makes
exactly one attempt to advance it — to the highest ordinal in the page whose episode
resolved, or to the page's highest where none did (§5), never computed from the
page's length. What the cursor buys is that repetition becomes **rare**; what makes
repetition *safe* is still ADR-0077 §8's fold, unchanged and not weakened here — a
repeat folds into a ``REINFORCE`` and the producer's confidence is deterministic on
its inputs, so a fold that takes the maximum finds nothing higher. No clause below
relies on the watermark for correctness of a re-observation.

**A conversation with no watermark starts at its tail** (ADR-0212 §4): the pass reads
ADR-0077 §8's window unchanged rather than walking forward from the first turn, which
is what keeps it from re-paying for turns a hand-run ``observe`` already read and from
grinding through an expired prefix. The turns below that first window are passed over
permanently, and the watermark asserts nothing about them.

Nothing concrete is imported: every collaborator arrives by injection and is seen
only through its Protocol (CLAUDE.md golden rule 1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.core.errors import UnknownConversationError, UnresolvedEvidenceError
from ai_assistant.core.types import (
    EpisodicMemory,
    Evidence,
    MemoryKind,
    ObservationReport,
    ObservedProposal,
    describe_untrusted,
)
from ai_assistant.orchestration.engine import learn_decision

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.protocols import (
        ConversationStore,
        MemoryStore,
        Observer,
    )
    from ai_assistant.core.types import (
        Conversation,
        ConversationTurn,
        LearnDecision,
        MemoryIngestResult,
        MemoryUpdateProposal,
    )
    from ai_assistant.orchestration.writes import MemoryWriteStage

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


def _check_citations(
    proposals: Sequence[MemoryUpdateProposal], *, batch: Mapping[str, str]
) -> None:
    """Refuse a proposal citing an episode the producer was never handed (§1, §5).

    **The scope limit, enforced where it is knowable.** ``Observer.observe`` owes
    that "every cited id is drawn from ``episodes``, and none from outside it", and
    the writer cannot enforce it: it sees a citation that *resolves* and has no idea
    which episodes were selected. Only this stage knows the batch, so a foreign id
    that happens to name a live record would otherwise be written as a warrant and
    rendered as evidence — pulling content out of a conversation the user never
    asked to observe, which is exactly the scope property ADR-0077 §1 makes a
    property of the seam rather than of one implementation's good behaviour.

    The unresolved half of the same fault already propagates through
    :class:`~ai_assistant.core.errors.UnresolvedEvidenceError` (§5). This closes the
    half the writer cannot see, so the fault behaves the same either way rather than
    depending on whether the foreign id happened to point at something.

    **Checked over the whole return value before anything is written.** It needs no
    store access, so interleaving it with the writes would buy nothing and risk a
    partial write for a fault that was knowable up front — and it is the producer's
    own validate-then-apply ordering (§4) applied one layer out.

    A ``ValueError`` rather than an ``AssistantError``, deliberately, and symmetric
    with the contract's other direction: the producer raises ``ValueError`` when the
    *stage* breaks the batch contract (an oversized batch, a repeated episode), and
    this is the stage raising it when the *producer* does. Both are wiring faults in
    an injected collaborator rather than conditions a user can act on — a conforming
    ``Observer`` cannot reach either — so neither is dressed up as a runtime failure
    to be rendered.

    Raises:
        ValueError: If any proposal cites an id outside ``batch``.
    """
    foreign = sorted(
        {
            cited
            for proposal in proposals
            for cited in proposal.proposed.provenance.evidence
            if cited not in batch
        }
    )
    if foreign:
        msg = (
            f"the observer cited {len(foreign)} episode(s) it was never handed "
            f"({', '.join(foreign)}); every citation must be drawn from the batch, "
            f"so nothing was ingested"
        )
        raise ValueError(msg)


def _marked(proposal: MemoryUpdateProposal, *, supplied_withheld: bool) -> MemoryUpdateProposal:
    """Stamp ADR-0204 §5's derivation marker on one proposal, discarding the producer's.

    **Assignment, never a disjunction with what the observer emitted**, which is the
    discipline ADR-0106 §3 fixes for the sibling marker and the reason it is stated:
    a merge would leave a code path in which a producer's claim about its own warrant
    reached the field, and the marker exists precisely because such a claim is not
    evidence of the standing it claims (ADR-0094 §5). The value this stage computes
    is a fact about the batch it selected, so it is written over whatever arrived.

    Args:
        proposal: What the observer proposed.
        supplied_withheld: The disjunction over the episodes this pass supplied it.

    Returns:
        The proposal, with the marker its stage computed.
    """
    provenance = proposal.proposed.provenance.model_copy(
        update={"supplied_withheld_content": supplied_withheld}
    )
    return proposal.model_copy(
        update={"proposed": proposal.proposed.model_copy(update={"provenance": provenance})}
    )


def observed_ruled(
    proposal: MemoryUpdateProposal,
    result: MemoryIngestResult,
    evidence: tuple[Evidence, ...] = (),
) -> ObservedProposal:
    """Pair a proposal with the ruling the write path returned for it.

    A module function rather than a constructor on the promoted model, like every
    projection in this package (ADR-0085 §6a): a projection from a ``core`` record
    into a ``core`` DTO belongs to the layer that *decides* it.
    """
    return _observed(
        proposal,
        decision=learn_decision(result.decision.kind),
        record_id=result.record_id,
        reason=result.decision.reason,
        evidence=evidence,
    )


def observed_unsupported(
    proposal: MemoryUpdateProposal, evidence: tuple[Evidence, ...] = ()
) -> ObservedProposal:
    """Record a proposal the write path refused for unresolved evidence.

    Reported rather than dropped in silence: a belief whose support went away
    under the observation is not stored, and saying so is the difference between
    an outcome the user can read and a count that went missing (ADR-0077 §5).
    """
    return _observed(
        proposal,
        decision=None,
        record_id=None,
        reason=_UNSUPPORTED_REASON,
        evidence=evidence,
    )


def _observed(
    proposal: MemoryUpdateProposal,
    *,
    decision: LearnDecision | None,
    record_id: str | None,
    reason: str,
    evidence: tuple[Evidence, ...],
) -> ObservedProposal:
    """Read the candidate half of a proposal, and pair it with an outcome.

    The one place a ``core``
    :class:`~ai_assistant.core.types.MemoryUpdateProposal` is read on the
    observation path, exactly as
    :func:`~ai_assistant.orchestration.engine.learn_outcome` holds that boundary on
    the learn path (ADR-0042 §1). Both entry points go through it, so a dropped
    proposal is rendered as fully as a ruled one.

    ``evidence`` is resolved by the stage rather than here, because resolving it is
    a read over the batch (and, on one unreachable path, over the store) while this
    is a pure projection — the same split
    :func:`~ai_assistant.orchestration.engine.belief_from_record` makes. It must
    carry one entry per citation, in order.
    """
    record = proposal.proposed
    provenance = record.provenance
    return ObservedProposal(
        content=record.content,
        kind=MemoryKind(record.kind),
        step=provenance.source,
        confidence=provenance.confidence,
        rationale=proposal.rationale,
        decision=decision,
        record_id=record_id,
        reason=reason,
        evidence=evidence,
    )


class ObservationStage:
    """Selects a batch of episodes, observes it, and ingests what comes back."""

    def __init__(  # noqa: PLR0913 — four injected collaborators plus the bound and the route label
        self,
        *,
        observer: Observer,
        conversations: ConversationStore,
        memory: MemoryStore,
        writes: MemoryWriteStage,
        batch_size: int,
        route: str,
    ) -> None:
        """Wire the stage from injected contracts.

        Three obligations no type can express, so each is the composition root's
        (ADR-0028 §4's shape, applied three times):

        * **``memory`` must be the store the write stage's writer persists to**,
          and the store
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
            conversations: The durable conversation index, read for the selection
                and written once per pass: the candidate listing, the page above a
                conversation's watermark, and the advance (ADR-0212 §§3, 5, 8).
            memory: Long-term memory, read to resolve each turn's episode. The same
                store the write stage's writer persists to.
            writes: The orchestration **write stage** — the memory write path
                (conflicts, the policy's ruling and the write in one call) plus the
                durable queue an ``ASK_USER`` ruling parks its question in
                (ADR-0078 §3). It holds the policy; this stage does not, and must
                not: "the model proposes, a deterministic policy disposes" is only
                true while the component selecting the batch cannot also rule on
                what comes back (ADR-0005 §3, ADR-0075 §2). It is the *stage* rather
                than a ``MemoryWriter`` of this stage's own because a producer's
                stage holding the writer directly would silently lose the queue —
                the second producer honouring ADR-0078 §3's one obligation.
            batch_size: How many of a conversation's turns one pass reads — the
                lowest that many above its watermark, or its most recent that many
                where it has none (ADR-0212 §§3, 4). A **maximum, not a quota**: a
                page containing a turn whose episode no longer resolves yields a
                shorter batch rather than reaching further forward (ADR-0077 §8,
                unchanged in value and in kind). It is the **only** count that bounds
                the page: `scheduler_chunk_size` does not reach this job, and an
                implementation handing it to ``turns_after`` or to
                ``conversations_with_unobserved_turns`` is not implementing ADR-0212.
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
        self._writes = writes
        self._batch_size = batch_size
        self._route = route

    async def observe(self, conversation_id: str | None = None) -> ObservationReport:
        """Observe one conversation's recent turns and ingest what they justify.

        The whole operation, in the order ADR-0077 §8 names: select, observe,
        ingest, report.

        **Selection is conversation-scoped and cursor-driven, and both halves are
        ratified rules rather than implementation details.** An id names the
        conversation; no id takes the **first candidate** from
        ``conversations_with_unobserved_turns`` — every conversation holding a turn
        above its watermark, least recently active first (ADR-0212 §3). "The newest N
        episodes in the store" was rejected explicitly, and so was "the most recently
        active conversation": the first re-reads the same N on every run and can
        never be asked for the N+1th, and the second would re-select whichever
        conversation the user happens to be using and never reach an idle one.

        **One pass observes one conversation, and reads the lowest page above its
        watermark** — at most ``batch_size`` turns, ordinal ascending, never the
        tail (§3) — except where the conversation has **no** watermark, when it reads
        ADR-0077 §8's tail window unchanged (§4). A run that wants more than one
        conversation performs more than one pass; no pass mixes two conversations'
        turns into one batch, because a batch is a prompt and two interleaved
        transcripts are a different thing to observe.

        **A turn whose episode does not resolve is skipped, and the batch is not
        backfilled** (ADR-0074 §5's rule, applied unchanged). Backfilling would make
        the page's *span* depend on how many gaps it contains, so two runs over one
        conversation would read different stretches of it.

        **An empty batch reaches no observer.** There is nothing to observe, no
        provider is called, and the report names no route (§9.7).

        **The advance is one attempt, at the end, and never computed from the page's
        length** (ADR-0212 §5). A pass that read a **non-empty** page makes exactly
        one ``record_observed`` call, after every proposal it produced has been ruled
        — even where the page resolved to no episode, even where the observer was not
        called, and even where nothing was proposed. It names the highest ordinal in
        the page whose episode **resolved**, or, where none did, the page's highest
        ordinal. That second branch is what stops a conversation whose unobserved
        turns have all expired re-reading one dead page for ever; it passes over
        nothing that was ever readable, since such a page reached no observer at all.
        A pass that read **no** turns makes **no** attempt and writes nothing: there
        is no ordinal for it to name.

        **The ordering is ADR-0111 §3's, not a choice.** The effects land in the
        memory store and the deferral queue, the watermark on the conversation index,
        and where they live in different stores the effects are made durable first —
        "a cursor that lags its effects costs repeated work; a cursor that leads them
        costs coverage, permanently and silently". So a pass that raises **before**
        its attempt moves the watermark by nothing and the whole page is re-read by
        the next pass that reaches that conversation, which is safe rather than
        merely tolerated: the repeat folds to a ``REINFORCE``. A pass that raises
        **at** its attempt leaves the stamp either committed or not, and both are
        safe — cancellation makes the ambiguity unavoidable rather than sloppy, and
        no compensating write, confirming re-read or in-pass retry is added, since
        each would be a second write to the watermark and none of them could tell the
        two states apart anyway (§6).

        **Two passes over one conversation may overlap, and nothing here serialises
        them.** Each computes its position from its own page and its own resolution
        of that page's episodes, and the two may legitimately differ. Overlap safety
        rests on ``record_observed``'s monotonicity and on nothing else: the higher
        position stands and the lower performs nothing (§5).

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
            conversation_id: The conversation to observe, or ``None`` for the first
                candidate. Untrusted input from an adapter, relayed to the store,
                which refuses an id it does not know rather than inventing a
                conversation for it. A named conversation with nothing above its
                watermark is a pass that reads no turns and writes nothing — the
                honest answer to "what has already been looked at", and the reason a
                repeated ``assistant observe <id>`` does nothing the second time
                (ADR-0212 §3; a deliberate re-observation is issue #1789).

        Returns:
            What was proposed, what became of each proposal, what was thrown away,
            and which route read the episodes.

        Raises:
            UnknownConversationError: If ``conversation_id`` names nothing, or names
                a conversation the user deleted.
            ConversationStoreError: If the conversation index cannot be read, or the
                watermark cannot be written.
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
                configured maximum, or carrying one episode twice — or if it
                returns a proposal citing an episode it was never handed, which
                this stage refuses before writing anything
                (:func:`_check_citations`). All three are wiring faults in an
                injected collaborator rather than user input: this stage selects at
                most ``batch_size`` distinct turns, and a conforming ``Observer``
                cites only what it was given.
        """
        target = await self._target(conversation_id)
        if target is None:
            return ObservationReport()
        page = await self._page(target)
        if not page:
            # No ordinal for this pass to name, so no attempt is made and nothing is
            # written anywhere (ADR-0212 §5). `None` is not a position and
            # `record_observed` refuses anything below the first ordinal before any
            # I/O, so there is nothing to call it with.
            return ObservationReport(conversation_id=target.id)
        episodes, through = await self._resolve(page)
        if not episodes:
            # The page reached no observer, so passing over it passes over nothing
            # that was ever readable — and advancing in one pass rather than one turn
            # at a time is what stops a conversation of expired turns becoming a
            # permanent candidate re-reading one dead page (ADR-0212 §5).
            await self._conversations.record_observed(target.id, through_ordinal=through)
            return ObservationReport(conversation_id=target.id)
        outcome = await self._observer.observe(episodes)
        # The batch *is* the evidence: every citation is drawn from it by contract,
        # so a proposal's warrant renders out of what was already read, with no
        # second pass over the store (ADR-0077 §5).
        batch = {episode.id: episode.content for episode in episodes}
        # Every proposal is checked against the batch **before any is written**. The
        # check needs no store access, so there is nothing to gain by interleaving it
        # with the writes and a partial write to lose — and it mirrors the producer's
        # own validate-then-apply ordering (§4).
        _check_citations(outcome.proposals, batch=batch)
        # ADR-0204 §5's derivation rule, computed from the batch this stage selected
        # and before anything is written — the shape ADR-0106 §3 already gives the
        # sibling marker on the consolidation path. The disjunction ranges over every
        # episode the producer was **supplied**, never over the subset it cited: an
        # observer that read a stamped episode and cited only clean ones would
        # otherwise emit a belief ADR-0199 §3 places speakable, which is #1708's
        # laundering with one distillation more in it.
        supplied_withheld = any(
            episode.provenance.supplied_withheld_content for episode in episodes
        )
        proposals: list[ObservedProposal] = []
        dropped = 0
        for proposal in outcome.proposals:
            entry = await self._ingest(
                _marked(proposal, supplied_withheld=supplied_withheld), batch=batch
            )
            if entry.decision is None:
                dropped += 1
            proposals.append(entry)
        # The pass's one and only write to the watermark, and it is the **last** act
        # of the pass: every proposal above has been ruled by the write path, so the
        # position records work that was done (ADR-0111 §3, ADR-0212 §5). The return
        # value is deliberately unread — `None` means an overlapping pass already
        # stands at or above this position, which is that rule working rather than a
        # condition to handle.
        await self._conversations.record_observed(target.id, through_ordinal=through)
        return ObservationReport(
            proposals=tuple(proposals),
            discarded_unusable=outcome.discarded_unusable,
            discarded_over_limit=outcome.discarded_over_limit,
            dropped_unsupported=dropped,
            route=self._route,
            conversation_id=target.id,
            episodes_read=len(episodes),
        )

    async def _target(self, conversation_id: str | None) -> Conversation | None:
        """The conversation this pass reads, or ``None`` when there is none.

        **The record rather than the id**, because the watermark travels on it: the
        page this pass reads is defined against ``observed_through`` (ADR-0212 §3,
        §4), and there is no operation on the seam that answers "where has the walk
        got to" apart from reading the conversation.

        Without an id the selector is the **head of a freshly-read candidate
        listing** — ``last_active_at`` ascending with ``id`` ascending as the
        tie-break, which ADR-0212 §3 makes a total order, so two implementations
        cannot disagree about which conversation is first. It is read afresh on every
        pass and never paged: a pass serves one conversation, and an offset over a
        set whose membership and whose ordering key both move between passes would
        skip or repeat a row.

        With an id, the store's ``get`` answers ``None`` for a conversation that is
        absent **and** for one stamped deleted — the two cases every presenting read
        on that contract refuses — so the stage turns that answer into the refusal
        this operation documents rather than reading no turns and reporting a quiet
        nothing. A deletion landing *after* this read is the race ADR-0212 §6 rules,
        and it surfaces from the page read or from the advance.

        Raises:
            UnknownConversationError: If ``conversation_id`` names nothing or names a
                conversation stamped deleted.
        """
        if conversation_id is None:
            candidates = await self._conversations.conversations_with_unobserved_turns(limit=1)
            return candidates[0] if candidates else None
        conversation = await self._conversations.get(conversation_id)
        if conversation is None:
            msg = f"no such conversation: {describe_untrusted(conversation_id)}"
            raise UnknownConversationError(msg)
        return conversation

    async def _page(self, conversation: Conversation) -> list[ConversationTurn]:
        """Read the turns this pass is to observe, ordinal ascending.

        Two reads and one rule (ADR-0212 §§3, 4): above a recorded watermark the page
        is the **lowest** ``batch_size`` turns strictly above it; with no watermark it
        is ADR-0077 §8's **tail** window unchanged, because walking a pre-existing
        conversation from its first turn would re-pay for turns a hand-run ``observe``
        already read and grind through an expired prefix before reaching anything
        live. The turns below that first window are then passed over permanently —
        stated at its true size in §4, and not a claim the watermark makes about them.
        """
        if conversation.observed_through is None:
            return await self._conversations.turns(conversation.id, limit=self._batch_size)
        return await self._conversations.turns_after(
            conversation.id,
            after_ordinal=conversation.observed_through,
            limit=self._batch_size,
        )

    async def _resolve(
        self, page: Sequence[ConversationTurn]
    ) -> tuple[tuple[EpisodicMemory, ...], int]:
        """Resolve a page into its batch of episodes and the position it advances to.

        The store's read-time axes do the filtering for free: ``get`` never returns
        an expired or non-live record and a deleted conversation's episodes are
        destroyed, so an episode the user has put beyond reach is beyond the
        observer's reach too, with no second filter to keep in step (ADR-0077 §1).

        A record that resolves but is not an episode is skipped like an id that does
        not resolve at all. The ``conv:`` namespace is reserved to captured
        conversation turns, so this is unreachable in practice; it is written
        because the alternative — handing a non-episode to a seam typed for
        episodes — would be a contract breach discovered inside the producer.

        **The position is computed here, from the page's ordinals and never from its
        length** (ADR-0212 §5). The page is ordinal ascending, so the last turn that
        resolved is the highest that did; where none resolved it is the page's own
        highest ordinal. A trailing gap therefore gets a second reading on the next
        pass and an interior one does not, which is the asymmetry §5 buys
        deliberately: where captures of one conversation are sequential an in-flight
        turn is always the newest, so the common case is covered by the rule itself.

        Args:
            page: The turns this pass read, ordinal ascending and **non-empty** —
                a pass over an empty page names no position at all and does not
                reach here.

        Returns:
            The resolved episodes in order, and the ordinal this pass advances to.
        """
        episodes: list[EpisodicMemory] = []
        resolved_through: int | None = None
        for turn in page:
            record = await self._memory.get(turn.episode_id)
            if isinstance(record, EpisodicMemory):
                episodes.append(record)
                resolved_through = turn.ordinal
        return tuple(episodes), page[-1].ordinal if resolved_through is None else resolved_through

    async def _ingest(
        self, proposal: MemoryUpdateProposal, *, batch: Mapping[str, str]
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
            DeferralStoreError: If a deferred question could not be parked. An
                observer's proposals reach nobody in the moment, so ADR-0078 §7
                promises this path nothing beyond reporting the failure to its own
                stage — which propagating does.
        """
        try:
            outcome = await self._writes.write(proposal)
        except UnresolvedEvidenceError as exc:
            unresolved = frozenset(exc.unresolved_ids)
            if not unresolved or not unresolved <= batch.keys():
                raise
            evidence = self._evidence(proposal, batch=batch, unresolved=unresolved)
            return observed_unsupported(proposal, evidence)
        evidence = self._evidence(proposal, batch=batch, unresolved=frozenset())
        return observed_ruled(proposal, outcome.result, evidence)

    @staticmethod
    def _evidence(
        proposal: MemoryUpdateProposal,
        *,
        batch: Mapping[str, str],
        unresolved: frozenset[str],
    ) -> tuple[Evidence, ...]:
        """Render one proposal's citations as readable evidence (ADR-0077 §4, §5).

        **Out of the batch, and only out of the batch.** Every citation is drawn from
        the episodes this pass selected — the contract's own rule, and one
        :func:`_check_citations` has already enforced before any write — so the
        content is in hand, resolving it costs no read at all, and **no id outside
        the batch can be dereferenced here.** That last part is the scope limit
        ADR-0077 §1 makes a property of the seam rather than of an implementation: a
        producer cannot reach an episode it was not handed, and it cannot reach one
        through this report either.

        ``unresolved`` names the citations the writer refused the proposal for. Those
        render as **tombstones**, and that is the honest rendering rather than a
        convenient one: the record is gone, and echoing the copy still sitting in
        this pass's batch would print back content the user may have just destroyed
        with ``forget-conversation``.
        """
        return tuple(
            Evidence() if cited in unresolved else Evidence(content=batch[cited])
            for cited in proposal.proposed.provenance.evidence
        )


__all__ = [
    "ObservationReport",
    "ObservationStage",
    "ObservedProposal",
]
