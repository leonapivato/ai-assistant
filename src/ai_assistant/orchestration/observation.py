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

There is no per-turn trigger: nothing waits on an observation while a turn does,
and ADR-0077 §8's first reason is kept whole (ADR-0218 §4). What there *is* is a
scheduled **run** — :meth:`ObservationStage.run`, behind ``Engine.observe_due`` —
which reads the candidate listing, applies ADR-0218 §2's due test in ADR-0212 §3's
order, and performs one pass against the first due candidate, until the listing it
last read holds none or its run budget is spent. A run is not a second trigger on
the turn path and it is not ambient machinery: it is the job ADR-0083 §7 put on the
scheduler's table, now armed by default (ADR-0218 §5).

**Due is quiet, aged, or full, and the third arm rests on no clock** (ADR-0218 §2).
A candidate is *quiet* when the run's clock instant minus its ``last_active_at``
reaches ``observation_quiet_window``; *aged* when that instant minus the
``occurred_at`` of its unobserved page's **first** turn reaches
``observation_max_unobserved_age``; and *full* when a whole page of
``observation_batch_size`` turns is available to read. The full arm is the
load-bearing one: ordinals are the store's own, allocated inside the step that
writes the row, so "does a whole page exist" is decided by counting rows and by
nothing a caller supplied — which is what bounds a conversation whose oldest
unobserved turn carries an ``occurred_at`` stamped ahead of the store's clock.

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

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import UnknownConversationError, UnresolvedEvidenceError
from ai_assistant.core.types import (
    EpisodicMemory,
    Evidence,
    LearnDecision,
    MemoryKind,
    ObservationReport,
    ObservedProposal,
    describe_untrusted,
)
from ai_assistant.orchestration.engine import learn_decision

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        ConversationStore,
        MemoryStore,
        Observer,
    )
    from ai_assistant.core.types import (
        Conversation,
        ConversationTurn,
        MemoryIngestResult,
        MemoryUpdateProposal,
    )
    from ai_assistant.orchestration.writes import MemoryWriteStage

#: Defaults for ADR-0218 §7's three run figures. All three are also
#: composition-root arguments, so an operator's ``Settings`` values win; these are
#: what the class does when nobody says, exactly as
#: :class:`~ai_assistant.orchestration.consolidation.ConsolidationStage` states its
#: own two.
DEFAULT_QUIET_WINDOW: Final = timedelta(minutes=10)
DEFAULT_MAX_UNOBSERVED_AGE: Final = timedelta(hours=2)
DEFAULT_RUN_BUDGET: Final = timedelta(minutes=5)

#: The rulings that **committed**: everything the write path did not refuse and did
#: not park as a question. Spelled as the complement of those two rather than as a
#: list of three, so a sixth :class:`~ai_assistant.core.types.LearnDecision` member
#: cannot quietly stop being counted at all.
_NOT_COMMITTED: Final = frozenset({LearnDecision.REJECTED, LearnDecision.DEFERRED})

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


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _check_duration(name: str, value: timedelta) -> None:
    """Refuse a run figure that is not an exact, strictly positive ``timedelta``.

    ``Settings`` refuses the same values at load — ADR-0218 §7 gives all three
    ``gt=timedelta(0)`` "in the form ADR-0083 §7 requires of every duration on this
    loop" — and this constructor is exported, so a caller wiring it directly would
    otherwise get behaviour §7 forbids. It is
    :func:`~ai_assistant.orchestration.consolidation._check_budget`'s guard applied
    to three fields instead of one, and for its reasons: ``timedelta(0)`` is the
    value that looks harmless and is not, because a zero budget spends itself before
    the first pass boundary and a zero quiet window makes every candidate quiet,
    which is the mid-conversation read ADR-0218 §1 exists to prevent.

    ``type(...) is timedelta`` rather than ``isinstance``, which closes the other
    end: a subclass overriding ``total_seconds`` to return infinity makes the run's
    deadline unreachable and the run unbounded. A native ``timedelta`` cannot hold a
    non-finite value, so excluding subclasses is the whole check rather than a first
    step.

    Raises:
        TypeError: If ``value`` is not exactly a ``timedelta``.
        ValueError: If it is not strictly positive.
    """
    if type(value) is not timedelta:
        msg = f"{name} must be a timedelta, got {type(value).__name__}: {value!r}"
        raise TypeError(msg)
    if value <= timedelta(0):
        msg = f"{name} must be strictly positive, got {value!r}"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ObservationRunReport:
    """What one scheduled observation run did (ADR-0218 §3).

    A frozen ``orchestration`` dataclass in
    :class:`~ai_assistant.orchestration.consolidation.ConsolidationReport`'s shape
    and for its reasons: it crosses no *subsystem* boundary, and every field is
    Tier 2 — counts and one disposition, no belief text, no route and no
    conversation id — so the whole of it is loggable under ADR-0004 §5.

    **Counts rather than reports, and §3 argues that rather than assuming it.** A
    run is bounded by *time* and not by a pass count, and its cheapest passes are
    its fastest, so "one :class:`~ai_assistant.core.types.ObservationReport` per
    pass" would be a list whose length is bounded by nothing in that ADR, holding
    Tier 1 proposal content, retained until the run returns, for a caller that
    discards it — ``service/scheduler.py``'s job body "return type is ``object``
    because the scheduler never looks at it". **Nothing here grows with the number
    of passes.**

    ``ObservationReport`` itself gains nothing and stays exactly what a *pass*
    returns to the CLI, which is what ADR-0212 §9 left standing.

    Attributes:
        passes: How many passes this run performed. A pass is ADR-0212 §3's pass,
            against a conversation this run **named**, so §3's "given none" default
            is not narrowed and a hand-run ``assistant observe`` still gets it.
        conversations: How many **distinct** conversations those passes served. Not
            the same figure as :attr:`passes`: a candidate with many pages of
            unobserved turns stays at the head of the ascending order and is served
            pass after pass until it is exhausted or the budget is spent, which is
            ADR-0212 §3's order working rather than a case to spread the budget over.
        episodes_read: How many episodes reached the producer, summed over the
            passes. Short of the pages read wherever a turn's episode no longer
            resolves, and zero for a run whose pages had all expired.
        model_calls: How many passes actually called the observer — at most one call
            per pass (ADR-0212 §3), and none at all for a page that resolved to no
            episode. It is the run's spend, which is the figure an operator arming
            a job on a cadence wants.
        proposed: How many proposals the observer returned, summed over the passes.
        committed: How many earned a committing ruling — stored, reinforced or
            superseded.
        deferred: How many the policy parked as a question for the user.
        rejected: How many the gate refused outright.
        dropped_unsupported: How many the **write path** refused because every
            episode they cited had stopped resolving between selection and the
            write. An ordinary consequence of a finite retention horizon, never a
            producer fault — a fault propagates instead.
        discarded_unusable: Model output the producer could not use, relayed
            unchanged and counted rather than repaired (ADR-0077 §4).
        discarded_over_limit: Usable beliefs the producer dropped to meet its
            configured maximum, counted apart from the unusable ones because the
            two are different facts about a run.
        budget_spent: Which of the **two** terminal reasons ended this run.
            ``True`` means ``scheduler_run_budget`` was spent; ``False`` means the
            listing the run last read held no due candidate — **never** a claim
            that the store holds none, which ADR-0218 §3 forbids any clause being
            read as. The two are exhaustive over the runs that *return*, which is
            why there is no third for a failure: a run whose pass raises returns no
            report at all (§9).
    """

    passes: int = 0
    conversations: int = 0
    episodes_read: int = 0
    model_calls: int = 0
    proposed: int = 0
    committed: int = 0
    deferred: int = 0
    rejected: int = 0
    dropped_unsupported: int = 0
    discarded_unusable: int = 0
    discarded_over_limit: int = 0
    budget_spent: bool = False


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

    def __init__(  # noqa: PLR0913 — four injected collaborators plus the route label, the page bound and the three run figures
        self,
        *,
        observer: Observer,
        conversations: ConversationStore,
        memory: MemoryStore,
        writes: MemoryWriteStage,
        batch_size: int,
        route: str,
        quiet_window: timedelta = DEFAULT_QUIET_WINDOW,
        max_unobserved_age: timedelta = DEFAULT_MAX_UNOBSERVED_AGE,
        run_budget: timedelta = DEFAULT_RUN_BUDGET,
        now: Clock = _utcnow,
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
            quiet_window: How long a conversation must have been inactive before a
                **scheduled** run reads it (ADR-0218 §1). It reaches :meth:`run`
                and nothing else: :meth:`observe` applies no due test, because an
                operator who typed the command has already decided it is time.
            max_unobserved_age: How long the oldest turn above a conversation's
                watermark may wait before a scheduled run reads it whether or not
                the conversation has gone quiet (ADR-0218 §2). Independent of
                ``quiet_window`` and not validated against it: a max age at or
                below the window makes the job a pure age trigger, which is a
                policy an operator can state (§7).
            run_budget: How long one :meth:`run` may spend before returning with
                work remaining. Checked **at a pass boundary**, so no pass is
                abandoned part-way and a run overruns by at most one pass
                (ADR-0111 §4, with the pass as the chunk).
            now: Clock for the due test, injectable for deterministic tests and
                guarded by :func:`~ai_assistant.core.clock.checked_clock`
                (ADR-0026 §7). It is **not** the budget's clock: that is the event
                loop's monotonic one, for the reason :meth:`run` gives.

        Raises:
            TypeError: If ``batch_size`` is not an integer, or any of the three
                durations is not exactly a ``timedelta``.
            ValueError: If ``batch_size`` is outside ``[1, 2**63)``, or any of the
                three durations is not strictly positive.
        """
        _check_batch_size(batch_size)
        _check_duration("quiet_window", quiet_window)
        _check_duration("max_unobserved_age", max_unobserved_age)
        _check_duration("run_budget", run_budget)
        self._observer = observer
        self._conversations = conversations
        self._memory = memory
        self._writes = writes
        self._batch_size = batch_size
        self._route = route
        self._quiet_window = quiet_window
        self._max_unobserved_age = max_unobserved_age
        self._run_budget = run_budget
        self._now = checked_clock(now, owner="ObservationStage")

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
        return await self._pass(target, await self._page(target))

    async def _pass(
        self, target: Conversation, page: Sequence[ConversationTurn]
    ) -> ObservationReport:
        """Observe one already-selected conversation's already-read page.

        The body of :meth:`observe` from the page down, factored out because a
        scheduled run selects and pages differently and must not read a turn twice
        to decide whether to read it (ADR-0218 §2). Everything below this line is
        the same act for both callers: what a pass *does* is ADR-0212 §3's pass and
        no clause of it is narrowed by being scheduled.

        Args:
            target: The conversation this pass serves, as the record rather than
                the id, because the watermark travels on it.
            page: The turns it reads, ordinal ascending, possibly empty.
        """
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

    async def run(self) -> ObservationRunReport:
        """Observe due conversations until none is due or the budget is spent (ADR-0218 §3).

        **One run performs zero or more passes.** Before each it reads the candidate
        listing afresh, applies §2's due test in ADR-0212 §3's order, and — where a
        due candidate exists **in that listing** — performs exactly one pass
        *naming that conversation's id*. So §3's optional-id branch is the one a
        scheduled pass takes, and §3's "given none" default stays exactly what a
        hand-run ``assistant observe`` gets.

        **A run establishes nothing about candidates beyond the listing's bound.**
        "No due candidate" is always a statement about the listing this run read and
        never about the store: the listing is a single call at ADR-0212 §8's bound of
        fifty, with no offset, no continuation and no widening, so a due candidate
        can sit beyond it. That takes more than fifty conversations having had a turn
        *begin* inside one quiet window — §1's monotonicity read backwards: if the
        head is not quiet then no candidate anywhere is quiet — and it is **accepted
        and named** rather than closed, because closing it is ``ConversationStore``
        surface and so a contract ADR of its own.

        **The budget is checked only at a pass boundary**, so a run overruns it by at
        most one pass — ADR-0111 §4 with the pass as the chunk. It is measured on the
        event loop's **monotonic** clock and never on the injected one, for the reason
        :meth:`~ai_assistant.orchestration.consolidation.ConsolidationStage.run`
        gives at length: a civil clock moved backwards by NTP or an operator would
        leave the deadline in the future for as long as the correction lasts, and a
        serial job would hold ADR-0083 §7's loop for exactly that long.

        **The run terminates, and the argument is ADR-0212 §5's.** Every candidate
        holds at least one turn above its watermark (§3), so every pass this run
        performs reads a non-empty page and makes exactly one advance attempt to a
        position strictly above the watermark it read — "the watermark never stands
        still across a pass over a non-empty page". Each pass therefore strictly
        shrinks the unobserved span of the conversation it served, and a conversation
        leaves the candidate set once its watermark reaches its highest turn. Turns
        arriving *during* a run remove only the **quiet** basis for due-ness, never
        the aged or full ones, and this run does not rest termination on them: where
        turns arrive faster than passes complete, what bounds the run is the budget.

        **One conversation may take the whole run, and that is the ordering
        working.** A candidate with many pages of unobserved turns stays at the head
        of the ascending order — no new turns, so no new activity instant — and is
        served pass after pass until it is exhausted or the budget is spent. ADR-0212
        §3 chose that order because "It serves the material nearest its expiry
        first", and spreading the budget would serve the material *furthest* from
        expiry with the same number of model calls. What the next run does is resume.

        **A pass that raises halts the run and the exception propagates** (§9), which
        is what makes the failure a failure: ``Scheduler._run_job`` decides its two
        dispositions by whether the job body raises, so a run that caught its pass's
        exception and returned a report saying so would be logged as a completed run
        with the fault's class recorded nowhere. Nothing durable is lost: the passes
        that completed already advanced their watermarks, and their counts are lost
        to a caller that discards them anyway. The one exception is the deletion
        race below.

        Returns:
            What the run did, in Tier 2 counts and one disposition. Every count zero
            is a **successful** run over a listing that held nothing due, and no
            caller may read it as a failure.

        Raises:
            ConversationStoreError: If the listing, a page or an advance could not
                be read or written.
            MemoryStoreError: If an episode could not be read, or the write path
                failed.
            ModelError: Propagated unwrapped from a pass's provider, its
                classification intact (ADR-0013 §5).
            DeferralStoreError: If a deferred question could not be parked.
            ValueError: If the injected clock's reading does not conform, or a
                producer breaks the batch contract.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._run_budget.total_seconds()
        served: set[str] = set()
        passes = episodes = calls = proposed = committed = deferred = rejected = 0
        unsupported = unusable = over_limit = 0
        budget_spent = False
        while True:
            # At a pass *boundary*, so no pass is abandoned part-way (ADR-0111 §4).
            if loop.time() >= deadline:
                budget_spent = True
                break
            selected = await self._due()
            if selected is None:
                break
            target, probed = selected
            try:
                page = (
                    probed
                    if probed is not None and target.observed_through is not None
                    else await self._page(target)
                )
                report = await self._pass(target, page)
            except UnknownConversationError:
                # The conversation was stamped deleted between the listing and the
                # read, which is an ordinary act the user performs (ADR-0074 §8) and
                # not a fault: the listing already excludes deleted conversations,
                # so this error is reachable from exactly one thing. It is caught,
                # the candidate is dropped, and the run continues (ADR-0218 §9,
                # partially superseding ADR-0212 §6's classification of it as a
                # failed pass). It cannot loop: the next listing no longer holds it.
                continue
            served.add(target.id)
            passes += 1
            episodes += report.episodes_read
            calls += 1 if report.episodes_read else 0
            proposed += len(report.proposals)
            committed += sum(
                1
                for entry in report.proposals
                if entry.decision is not None and entry.decision not in _NOT_COMMITTED
            )
            deferred += sum(
                1 for entry in report.proposals if entry.decision is LearnDecision.DEFERRED
            )
            rejected += sum(
                1 for entry in report.proposals if entry.decision is LearnDecision.REJECTED
            )
            unsupported += report.dropped_unsupported
            unusable += report.discarded_unusable
            over_limit += report.discarded_over_limit
        return ObservationRunReport(
            passes=passes,
            conversations=len(served),
            episodes_read=episodes,
            model_calls=calls,
            proposed=proposed,
            committed=committed,
            deferred=deferred,
            rejected=rejected,
            dropped_unsupported=unsupported,
            discarded_unusable=unusable,
            discarded_over_limit=over_limit,
            budget_spent=budget_spent,
        )

    async def _due(self) -> tuple[Conversation, list[ConversationTurn] | None] | None:
        """The first due candidate in one freshly-read listing, and the page it read.

        **The listing is walked in ADR-0212 §3's order and the first due candidate
        is taken** (ADR-0218 §2). It is never re-sorted, and a later due candidate is
        never preferred over an earlier one on the ground that its span is older or
        its page fuller.

        **The clock is read once, for the whole walk.** §1's decisive property is
        that quietness is monotone decreasing in ``last_active_at`` ascending, so for
        a **fixed** instant the quiet candidates are a prefix of the order exactly —
        which is what makes a quiet head the answer without a scan, and what a
        second reading part-way down the walk would quietly break.

        **A quiet head costs no probe at all**, which is the ordinary case: the head
        is quiet exactly when any candidate is quiet. The other two arms cost one
        bounded ``turns_after`` per candidate examined, so a run pays at most fifty
        bounded index reads before it selects, with no model call and no embedding
        among them — and those are paid only on a tick where nothing is quiet, which
        is exactly the state the backstop exists to resolve.

        Returns:
            The due candidate and the page read to decide it, or ``None`` when this
            listing held none. The page is ``None`` where the **quiet** arm decided
            it, since no probe was read — which is not the same fact as a probe that
            came back empty.
        """
        now = self._now()
        candidates = await self._conversations.conversations_with_unobserved_turns()
        for candidate in candidates:
            if now - candidate.last_active_at >= self._quiet_window:
                return candidate, None
            try:
                page = await self._conversations.turns_after(
                    candidate.id,
                    after_ordinal=candidate.observed_through,
                    limit=self._batch_size,
                )
            except UnknownConversationError:
                # The same deletion race one call earlier: stamped between the
                # listing and the probe rather than between the probe and the pass.
                # The candidate is dropped and the walk carries on, for ADR-0218 §9's
                # reason — a user's ordinary act is not a fault, and this one has not
                # even reached a pass.
                continue
            if self._aged(page, now=now) or self._full(page):
                return candidate, page
        return None

    def _aged(self, page: Sequence[ConversationTurn], *, now: datetime) -> bool:
        """Whether this candidate's unobserved span has waited too long (ADR-0218 §2).

        **The span begins at the page's *first* turn**, which is its oldest
        unobserved one. The question the arm asks is "has material been waiting too
        long", and measuring on ``last_active_at`` would make an actively-used
        conversation permanently *not* aged — the case the arm exists for — while
        measuring on the newest unobserved turn would do the same thing one turn
        later. The oldest is the only one of the three that ages.

        ``occurred_at`` is the **caller's** instant and this project never promises
        a monotonic clock, so a turn stamped ahead of the store's clock has a
        negative age and this arm does not fire until the store's clock catches up.
        That is why it is not the only arm: :meth:`_full` rests on no instant at all.
        Using a caller's instant here is not ADR-0111 §2's excluded shape either —
        nothing here is a *position*; the walk's position is ADR-0212's ordinal
        watermark, and this decides only whether to walk now.
        """
        return bool(page) and now - page[0].occurred_at >= self._max_unobserved_age

    def _full(self, page: Sequence[ConversationTurn]) -> bool:
        """Whether a whole page is available to read (ADR-0218 §2).

        **The arm that rests on no clock, and the load-bearing half of the
        backstop.** Ordinals are the store's own — dense, unique and monotonic,
        allocated inside the same indivisible step that writes the row — so this is
        decided by counting rows and by nothing a caller supplies. What it bounds is
        counted in **recorded** turns rather than in elapsed time: a candidate is due
        here once ``observation_batch_size`` turns have been recorded above its
        watermark, whatever any caller stamped on any of them.

        The comparison is ``>=`` where ADR-0218 §2 says "exactly": ``turns_after``
        bounds its page at ``limit``, so the two are the same test, and the
        inequality is the direction that fails safe if a store ever returned more.
        """
        return len(page) >= self._batch_size

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
    "ObservationRunReport",
    "ObservationStage",
    "ObservedProposal",
]
