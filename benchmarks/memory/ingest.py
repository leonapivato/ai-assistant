"""Put one case's conversation through the real capture and distillation path.

**The cadence is interleaved, and that is forced rather than chosen.**
``ObservationStage`` reads *the conversation's most recent ``batch_size`` turns* —
a window, not a cursor, which ADR-0083 §13 records as the reason the scheduler's
observation job ships disabled. Capturing 300 turns and then calling ``observe``
once would distil the last twenty and never see the other 280. So the driver
captures a batch, observes it, captures the next, observes that: the full windows
tile, and the pass count is the honest cost of ingesting that case.

**And consecutive windows overlap by design, not only at the end** (ADR-0162 §7).
The last *k* **episodes** of one window are the first *k* of the next. Where every
turn resolves that is simply a pass every ``batch_size - k`` captures; where one does
not it is not, because the stage's window is ``batch_size`` *turns* and skips a turn
whose episode no longer resolves (ADR-0074 §5). So the driver records which turn
positions stored an episode and schedules the next pass to *begin* at the position of
the current window's *k*-th episode from the end, which delivers the clause with a gap
in the window or without one. The loss it closes is a fact stated across a window
boundary — the
user names a trip in the last turn of one window and says where they went in the
first turn of the next, visible to neither pass as a whole. Under ADR-0077 §2's
warrant bar that was rare, because a fragment cleared the bar seldom enough to be
noise; under ADR-0162 §1 every fragment is proposable, so a boundary now cuts through
material that would otherwise have been recorded, at a rate set by an arbitrary
alignment rather than by the data.

The duplication it buys costs almost nothing, because it is already solved: ADR-0077
§3 puts de-duplication at the gate deterministically and locally, ADR-0121 §1's
``agrees`` predicate decides a verbatim restatement with no model call, and ADR-0159
§3's first rung labels it ``RESTATES`` unconditionally, folding to a ``REINFORCE``
that finds nothing higher. An episode carried in by the overlap is a **full member**
of the window it is carried into — labelled, rendered and citable exactly as any
other — which is what makes the shape cheaper than the alternative of showing the
previous tail as un-proposable context.

**The last window overlaps, and it cannot be made not to.** A case whose turn count is
not a multiple of the batch ends with a remainder, and the window is always *the most
recent ``batch_size``* — there is no offset on the read — so the closing pass re-reads
``batch_size - remainder`` turns an earlier pass already distilled. The alternative is
to skip the closing pass, and that is worse in the case that matters most: a
LongMemEval haystack is often shorter than one batch outright, so skipping would
ingest a conversation and distil nothing from it. The overlap is therefore taken and
**counted** — :attr:`IngestionSummary.episodes_reobserved` — rather than hidden, since
it is a real token cost and a real second chance for the observer to propose the same
belief twice.

**A benchmark turn is not always an exchange, and it depends on what the session
is.** Capture records one episode per turn, with a user half and an assistant half.
Two shapes reach it, and :attr:`~benchmarks.memory.cases.BenchSession.user_supplied`
says which:

*A conversation the user actually had* — LongMemEval — folds into exchanges. It does
not guarantee strict alternation: a speaker can take two turns running, and five of
LongMemEval's oracle sessions open on the assistant. So consecutive same-side
utterances are joined into one half, and a session that opens on the assistant side
has that run recorded as a turn of its own with no user half. Neither case is
silently smoothed: both are counted in the summary, because a corpus where they were
common would be one whose ingestion is not saying what a reader assumes.

*A transcript the user supplied* — LoCoMo, under #1177's framing — has no assistant
half anywhere in it, so there is nothing to pair and the fold above would join a
whole session into one episode. It yields **one exchange per corpus turn**, each with
``outcome=None``, and the pairing is bypassed rather than coincidentally producing
that result: it is the session's declared shape, not an accident of every turn
sharing a side. Three things follow, and all three are the point. The observation
windows still tile over *turns*, so ``observation_batch_size`` means what it meant.
#1074's evidence join stays one corpus turn to one episode, which is the finest
resolution it can have. And ``assistant_led_turns`` is 0 for such a corpus by
construction — the summary says the assistant led none of it, which is true, where
the old ``speaker_b``-as-assistant mapping made it say the assistant led half.

**Ingestion is the only place a corpus evidence pointer and a captured episode id are
both in hand, so this is where the two are written down** (#1074). A question's
``evidence`` names corpus turns; a retrieval returns generated record ids; and the
bridge between the two id spaces is "which episode did this corpus turn become",
which capture reports once, here, and nowhere afterwards.
:attr:`IngestionSummary.evidence_episodes` keeps it, so P8's "the evidence was
retrieved and the reader failed" versus "the evidence was never retrieved" is
computable from the run's own records rather than from stores a default run deletes.

**Every ``ASK_USER`` ruling is counted, and none is answered.** Benchmark ingestion is
headless: the policy's deferrals become questions nobody will ever be asked, so the
belief is not written and the retrieval that would have found it cannot. That is a
property of the *harness*, not of the pipeline under test, so it is measured rather
than worked around — see :attr:`IngestionSummary.proposals_deferred` for why
auto-answering was rejected outright.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import LearnDecision

if TYPE_CHECKING:
    from collections.abc import Sequence

    from benchmarks.memory.cases import BenchCase, BenchSession, BenchTurn
    from benchmarks.memory.wiring import Harness

__all__ = ["Exchange", "IngestionSummary", "exchanges_of", "ingest_case"]

#: How many episodes consecutive observation windows share, nominally (ADR-0162 §7).
#:
#: **A module constant rather than a ``Settings`` field, and the argument is the one
#: §13 hands the lane.** The test is whether the right value is a thing an operator
#: can know about their own corpus — which is why ``observation_max_proposals`` is a
#: setting (ADR-0077 §2) and ``EPISODIC_SUPPLEMENT_LIMIT`` is not (ADR-0158 §5). It
#: is not. §7 says in terms that the value inside its bound is "an empirical question
#: about how far a fact spreads across turns, which no run has measured", so there is
#: nothing for an operator to know it against; and the clause binds the benchmark
#: harness's ingestion driver, which no deployment runs — the product's
#: explicit-trigger path tiles nothing (§7's fifth clause, ADR-0077 §8). A setting
#: would therefore offer an operator a knob onto a code path they do not have. When
#: a durable-cursor walk (ADR-0111 §1) inherits §7 and a run has measured the spread,
#: that lane is the one with a consumer for a configured value.
#:
#: **Why 4.** §7 bounds *k* at ``observation_batch_size // 2`` because the re-read
#: cost is exactly ``batch / (batch - k)`` passes over a corpus, so half the batch
#: doubles ingestion spend. At the default batch of 20, 4 costs 20/16 = 1.25 times the
#: passes and guarantees that **any fact spread over at most five consecutive turns
#: is whole in some window**: windows start every ``batch - k`` turns and run
#: ``batch`` long, so a run of length ``L`` starting anywhere is contained in one
#: whenever ``L <= k + 1``. That is a property worth stating rather than a taste, and
#: it is the shape a later measurement of the real spread would revise.
_TILE_OVERLAP: Final = 4


def _overlap_of(batch_size: int) -> int:
    """How many episodes consecutive windows share, for this ``batch_size``.

    :data:`_TILE_OVERLAP`, clamped into ADR-0162 §7's bound of at least 1 and at most
    ``batch_size // 2``. The clamp is not defensive: ``observation_batch_size`` is a
    positive ``Settings`` field with no upper bound near this one, and the harness's
    own tests run batches of 1 and 2.

    **At a batch of 1 the answer is 0, which §7 rules explicitly rather than leaving
    to the arithmetic.** The bound is empty there and the deployment forgoes the
    section's remedy: an overlap of 1 on a window of 1 advances the tiling by nothing,
    so no value satisfies progress and overlap together. ``1 // 2`` is 0, so the
    expression states that case rather than special-casing it.
    """
    return min(_TILE_OVERLAP, batch_size // 2)


@dataclass(frozen=True, slots=True)
class Exchange:
    """One turn as capture takes it.

    Attributes:
        content: The user half. Never blank — capture refuses a blank one, and the
            builder below never produces one.
        outcome: The assistant half, or ``None`` where the session ended on the user
            — or, for a session the user *supplied*, where there is no assistant half
            at all and every exchange takes ``None``.
        user_led: Whether ``content`` is genuinely the user's side. ``False`` marks
            the orphan case: an assistant run with no user turn before it, recorded
            in the user half because that is the only half capture requires.
        evidence_keys: The corpus pointers of every turn folded into this exchange,
            in order and without repeats. **Plural because the fold is many-to-one**:
            consecutive same-side utterances join into one half, and the two halves
            are two runs, so one episode can be several cited turns at once. Every
            one of them maps to the single episode this exchange becomes, which is
            the honest resolution — the harness cannot cite half an episode. Where
            the session was supplied by the user there is no fold, so this holds at
            most the one turn's own pointer.
    """

    content: str
    outcome: str | None
    user_led: bool
    evidence_keys: tuple[str, ...] = ()


@dataclass(slots=True)
class IngestionSummary:
    """What ingesting one case cost and produced.

    Attributes:
        conversation_id: The conversation the case was captured under.
        turns_captured: Exchanges capture accepted.
        turns_degraded: Exchanges capture reported as unrecorded. Non-zero here means
            the run's memory is missing episodes and any score from it is suspect.
        assistant_led_turns: Orphan runs — see this module's docstring. Zero for a
            corpus of user-supplied transcripts, where the assistant led nothing.
        observation_passes: Calls to ``ObservationStage.observe``, which is also the
            number of model calls distillation made.
        episodes_read: Episodes those passes were shown, summed.
        proposals: Beliefs the observer returned, summed.
        discarded_unusable: Relayed from the producer.
        discarded_over_limit: Relayed from the producer.
        dropped_unsupported: Proposals the write path refused for unresolved evidence.
        proposals_deferred: Proposals the memory policy ruled ``ASK_USER`` on.

            **The declared disposition is: counted, and never answered.** Benchmark
            ingestion is headless, so a deferral's question is parked in a queue no
            one reads and the belief is never written — and the queue is bounded
            (``ASSISTANT_DEFERRAL_QUEUE_LIMIT``, 50 by default), so past the cap even
            the question is refused. Auto-answering them was considered and rejected:
            the harness would then be ruling on proposals it also produced, which is
            precisely the separation ADR-0005 §3 keeps ("the model proposes, a
            deterministic policy disposes"), and any rule for answering would be a
            *policy change* whose effect would be reported as a result of the pilot.
            So the artifact is measured instead of removed, and #1029's P3 and P5 are
            read against :attr:`ask_rate` — a depressed recall over a case with a
            non-zero ask rate is attributable here rather than to retrieval.

            This counts **rulings**, not queue admissions, exactly as
            ``IngestionReport.deferred`` does and for the same reason: three write
            outcomes rule ``ASK_USER`` and enqueue nothing, so saying "a question is
            waiting" would be false for them.
        observation_routes: Every model route that read episodes. More than one means
            the configuration moved mid-run, which invalidates the case.
        evidence_episodes: Each corpus evidence pointer this case ingested, mapped to
            the captured episode ids it became, in capture order (#1074). A pointer
            absent from the mapping never became an episode in this run — it named a
            turn outside the ingested slice (``--max-sessions``), or its capture
            degraded, or the corpus gave the turn no pointer at all.
    """

    conversation_id: str
    turns_captured: int = 0
    turns_degraded: int = 0
    assistant_led_turns: int = 0
    observation_passes: int = 0
    episodes_read: int = 0
    proposals: int = 0
    discarded_unusable: int = 0
    discarded_over_limit: int = 0
    dropped_unsupported: int = 0
    proposals_deferred: int = 0
    observation_routes: set[str] = field(default_factory=set)
    evidence_episodes: dict[str, list[str]] = field(default_factory=dict)

    @property
    def episodes_reobserved(self) -> int:
        """Episodes a pass read that an earlier pass had already read.

        The closing partial window's overlap — see this module's docstring. Zero when
        the turn count is a multiple of the batch size, and at most ``batch_size - 1``
        otherwise.

        Returns:
            The count.
        """
        return max(0, self.episodes_read - self.turns_captured)

    @property
    def proposals_ruled(self) -> int:
        """Proposals a policy actually ruled on.

        Everything the observer returned, minus the ones the write path refused for
        unresolved evidence before any policy saw them (ADR-0077 §5). That is the
        population an ask rate is a rate *of*: a dropped proposal was never eligible
        to be deferred, so leaving it in the denominator would understate the ask rate
        by exactly the amount the run was already degraded.

        Returns:
            The count.
        """
        return max(0, self.proposals - self.dropped_unsupported)

    @property
    def ask_rate(self) -> float:
        """The share of ruled proposals the policy wanted a human answer for.

        Zero when nothing was ruled on, which is the honest reading: a case that
        proposed nothing did not ask anything either, and a rate over an empty
        population would be undefined rather than zero if anyone divided it.

        **It is not a score and cannot be read as one.** It measures the harness's own
        headlessness — how much of what the observer proposed went unwritten because
        nobody was there to answer — and says nothing about whether an answer was
        right. #1029's ground rule 1 is about the latter.

        Returns:
            The rate, in ``[0, 1]``.
        """
        ruled = self.proposals_ruled
        return self.proposals_deferred / ruled if ruled else 0.0

    @property
    def evidence_keys_captured(self) -> int:
        """How many distinct corpus evidence pointers became at least one episode.

        The denominator a reader needs before believing an empty join: a case whose
        pointers all failed to map has a P8 split that is missing rather than
        negative.

        Returns:
            The count.
        """
        return len(self.evidence_episodes)


def exchanges_of(session: BenchSession) -> tuple[Exchange, ...]:
    """Fold a session's utterances into the exchanges capture records.

    Two shapes, chosen by :attr:`~benchmarks.memory.cases.BenchSession.user_supplied`
    — see this module's docstring.

    Where the session is a conversation the user had, each exchange carries the
    evidence keys of **every** turn that went into it, both halves included: the fold
    is many-to-one, so a citation to any of those turns is a citation to the one
    episode they become (#1074).

    Where it is a transcript the user supplied, there is no fold: one turn is one
    exchange, carrying that turn's own key and no assistant half. ``user_led`` is
    ``True`` for every one of them, and that is a guarantee rather than an
    assumption — :class:`~benchmarks.memory.cases.BenchSession` refuses to construct
    a supplied session holding a turn that is not user-side, so there is no state
    here in which the summary could call an utterance assistant-led while capture
    stored it as the user's.

    Args:
        session: The session.

    Returns:
        The exchanges, in order. Empty for a session with no turns.
    """
    if session.user_supplied:
        return tuple(
            Exchange(
                content=turn.text,
                outcome=None,
                user_led=True,
                evidence_keys=() if turn.evidence_key is None else (turn.evidence_key,),
            )
            for turn in session.turns
        )

    runs: list[_Run] = []
    for turn in session.turns:
        if runs and runs[-1].user_side == turn.user_side:
            runs[-1].add(turn)
        else:
            runs.append(_Run.of(turn))

    built: list[Exchange] = []
    index = 0
    while index < len(runs):
        run = runs[index]
        if not run.user_side:
            # An assistant run with nothing before it. Recorded rather than dropped:
            # LongMemEval's assistant turns carry evidence (#1029's P6), and losing
            # them would answer P6 by construction instead of by measurement.
            built.append(
                Exchange(
                    content=run.text,
                    outcome=None,
                    user_led=False,
                    evidence_keys=_distinct(run.keys),
                )
            )
            index += 1
            continue
        following = runs[index + 1] if index + 1 < len(runs) else None
        built.append(
            Exchange(
                content=run.text,
                outcome=following.text if following is not None else None,
                user_led=True,
                evidence_keys=_distinct(
                    run.keys + (following.keys if following is not None else [])
                ),
            )
        )
        index += 2 if following is not None else 1
    return tuple(built)


@dataclass(slots=True)
class _Run:
    """Consecutive utterances from one side, accumulated as they are folded.

    A named accumulator rather than a tuple of parallel lists: the fold now carries
    three things per run and a positional triple is where a reader stops being able to
    tell which list is which.
    """

    user_side: bool
    texts: list[str]
    keys: list[str]

    @classmethod
    def of(cls, turn: BenchTurn) -> _Run:
        """Start a run at ``turn``.

        Args:
            turn: The first utterance of the run.

        Returns:
            The run.
        """
        run = cls(user_side=turn.user_side, texts=[], keys=[])
        run.add(turn)
        return run

    def add(self, turn: BenchTurn) -> None:
        """Fold one more utterance of the same side in.

        Args:
            turn: The utterance.
        """
        self.texts.append(turn.text)
        if turn.evidence_key is not None:
            self.keys.append(turn.evidence_key)

    @property
    def text(self) -> str:
        """The run's utterances, joined as capture takes them."""
        return "\n".join(self.texts)


def _distinct(keys: Sequence[str]) -> tuple[str, ...]:
    """The keys in first-seen order, without repeats.

    Order-preserving rather than ``sorted(set(...))``: the mapping this feeds is read
    as "the episodes this pointer became, in capture order", and a pointer set
    reordered per exchange would make that claim about the wrong sequence.

    Args:
        keys: The keys, possibly with repeats.

    Returns:
        The distinct keys.
    """
    seen: dict[str, None] = dict.fromkeys(keys)
    return tuple(seen)


async def ingest_case(harness: Harness, case: BenchCase, *, batch_size: int) -> IngestionSummary:
    """Capture and distil one case's whole conversation.

    Args:
        harness: The wired pipeline. Its clock is moved to each session's instant
            before that session is captured.
        case: The case to ingest.
        batch_size: How many captured turns an observation pass reads. Must be the
            same value the harness's ``ObservationStage`` was built with, or the
            windows stop tiling — pass ``settings.observation_batch_size``. It is
            also what :func:`_overlap_of` reads the window overlap off, for the same
            reason: the overlap is a fraction of the window, and a driver computing
            it from a different number would not be describing the stage's window.

    Returns:
        What it cost and produced.

    Raises:
        ValueError: If ``batch_size`` is not positive, which would make the tiling
            below loop without progress.
    """
    if batch_size < 1:
        msg = f"batch_size must be positive, got {batch_size}"
        raise ValueError(msg)
    overlap = _overlap_of(batch_size)

    # The clock is set before `begin`, because starting a conversation stamps it.
    harness.clock.set(case.sessions[0].occurred_at)
    conversation = await harness.lifecycle.begin(None)
    summary = IngestionSummary(conversation_id=conversation.id)

    # **The schedule is kept in turn positions, and the overlap is measured in
    # episodes.** ADR-0162 §7's clause is about episodes — "the last *k* episodes of
    # one window are the first *k* of the next" — while ``ObservationStage``'s window
    # is the conversation's most recent ``batch_size`` **turns** and it skips a turn
    # whose episode no longer resolves, without backfilling (ADR-0074 §5). Where every
    # turn resolves the two are the same sequence and a pass every ``batch_size -
    # overlap`` captures satisfies §7 exactly. Where one does not, they diverge: a
    # window of ``batch_size`` turns holding a gap carries fewer than ``overlap``
    # episodes into the next one, and the clause quietly under-delivers.
    #
    # So the driver records **which turn positions landed an episode** and schedules
    # off those. After a pass over turns ``[start, turns]`` it takes that window's
    # episode-bearing positions, picks the ``overlap``-th from the end, and fires the
    # next pass when the window would *begin* there — which makes exactly those
    # ``overlap`` episodes the next window's prefix, gap or no gap. ``_next_pass_at``
    # is that arithmetic and nothing else.
    #
    # **A capture that stored nothing buys no pass of its own.** A lost append records
    # no turn at all and an episode write that never landed leaves an unresolvable
    # one, so a stretch of them adds nothing a pass could read while still advancing
    # the position counter — and at the extreme the pass re-reads exactly the window
    # the last one read: a duplicate model call, on a paid run, proposing what the
    # gate will fold. That was already reachable before §7 after ``batch_size`` such
    # captures in a row and the overlap makes it reachable sooner, so the trigger asks
    # whether an episode has landed since the last pass. It is keyed on the episode id
    # alone rather than on ``degraded``, which is the conservative direction: a report
    # that is degraded and still carries an id has something a pass can read.
    #
    # **That gate postpones a pass and never cancels one.** ``turns`` still counts
    # every capture, for the reason below, so postponing can carry it past the
    # scheduled position — hence ``>=`` rather than ``==``. Nothing readable is
    # skipped: a stretch that skipped a pass is by construction a stretch in which
    # nothing was stored, and the pass fires on the first capture that lands.
    #
    # **The positions are capture counts, so the schedule is exact for every failure
    # this driver can see and approximate for the one it cannot.** An episode-stage
    # failure leaves the turn appended, so a position is still a turn and the
    # arithmetic above delivers §7's identity with the gap in it. A *lost append*
    # records no turn at all, and `CaptureReport` reports the two identically — that
    # is #1075, whose title says in terms that a driver's cadence needs the
    # distinction — so under one the positions run ahead of the conversation.
    #
    # The direction of that error is the pre-existing safe one the comment below
    # argues for, and it is worth stating as a bound rather than left as "approximate":
    # over-counting fires a pass *earlier* in real turns than intended, so the next
    # window begins at or before the episode the carry aimed at and therefore still
    # **contains** the whole carried tail — §7's remedy is delivered, and what is lost
    # is only its position as the window's literal prefix, plus some duplicated passes.
    # Closing it exactly needs #1075 and a change in `orchestration`, which is not this
    # module's to make; a floor on the schedule would buy the append case by breaking
    # the episode-stage case, because the driver cannot tell which one it is in.
    turns = 0
    landed: list[int] = []
    observed_through = 0
    next_at = batch_size
    for session in case.sessions:
        harness.clock.set(session.occurred_at)
        for exchange in exchanges_of(session):
            report = await harness.lifecycle.capture(
                conversation.id, content=exchange.content, outcome=exchange.outcome
            )
            # **Counted before it is classified, because the window counts turns and
            # this loop cannot see which kind of degradation it got.** `capture` writes
            # the index entry first and the episode second, so an episode-stage failure
            # leaves a turn in the conversation carrying an id that no longer resolves.
            # `ObservationStage` reads the most recent `batch_size` *turns* and skips an
            # unresolvable one **without backfilling** (ADR-0074 §5), so that turn still
            # holds a slot. Pacing on successful captures alone would therefore let an
            # earlier, perfectly good episode fall out of every window that is ever
            # read — never distilled, and silently, which biases the very retrieval the
            # pilot measures.
            #
            # A lost *append* records no turn and holds no slot, but `CaptureReport`
            # reports both failures identically (#1075), so this counts every capture
            # and takes the safe direction: `batch_size` is "a maximum, not a quota",
            # so over-counting under-fills a window, where under-counting drops
            # episodes.
            turns += 1
            # Recorded off the episode id alone rather than off the branch below,
            # which is the conservative direction: a report that is `degraded` and
            # still carries an id has something a pass can read.
            if report.episode_id is not None:
                landed.append(turns)
            if report.degraded or report.episode_id is None:
                summary.turns_degraded += 1
            else:
                summary.turns_captured += 1
                if not exchange.user_led:
                    summary.assistant_led_turns += 1
                # #1074's join, written at the only moment both halves exist. A
                # degraded capture is deliberately *not* recorded above: it has no
                # episode id to point at, and an entry mapping a pointer to nothing
                # would read as "retrieved nothing" where the truth is "was never
                # stored".
                for key in exchange.evidence_keys:
                    summary.evidence_episodes.setdefault(key, []).append(report.episode_id)
            if turns >= next_at and landed and landed[-1] > observed_through:
                await _observe(harness, conversation.id, summary)
                next_at = _next_pass_at(
                    landed, through=turns, batch_size=batch_size, overlap=overlap
                )
                observed_through = turns
    if landed and landed[-1] > observed_through:
        await _observe(harness, conversation.id, summary)
    return summary


def _next_pass_at(landed: Sequence[int], *, through: int, batch_size: int, overlap: int) -> int:
    """The turn position at which the next pass's window begins where §7 asks.

    A pass has just read the turns ``[through - batch_size + 1, through]``. ADR-0162
    §7 requires the last ``overlap`` **episodes** of that window to be the first
    ``overlap`` of the next, so the next window must *begin* at the position of this
    window's ``overlap``-th episode from the end — and a window of ``batch_size``
    turns beginning there ends ``batch_size - 1`` later, which is the answer.

    Args:
        landed: Every turn position that stored an episode, in order.
        through: The last turn position the pass just read.
        batch_size: The window, in turns.
        overlap: §7's *k*, already clamped into its bound by :func:`_overlap_of`.

    Returns:
        The turn count at which the next pass is due.

    **The two degenerate cases carry no overlap, and both are §7's own.** An
    ``overlap`` of 0 is the batch of 1 the section rules explicitly, and a window that
    held *fewer* than ``overlap`` episodes has a gap wider than the carry — in both
    the next window starts after this one ends, which is the pre-§7 tiling rather than
    a breach of it. A window that held some but fewer than ``overlap`` carries all of
    them, which is the most §7 can ask of it.
    """
    if overlap == 0:
        return through + batch_size
    window = [position for position in landed if position > through - batch_size]
    if not window:
        return through + batch_size
    return window[max(0, len(window) - overlap)] + batch_size - 1


async def _observe(harness: Harness, conversation_id: str, summary: IngestionSummary) -> None:
    """Run one observation pass and fold its report into ``summary``.

    Args:
        harness: The wired pipeline.
        conversation_id: The conversation to observe. Passed explicitly rather than
            letting the stage select "the most recently active", because selection
            reads the conversation index and this driver already knows the answer.
        summary: Accumulated in place.
    """
    report = await harness.observation.observe(conversation_id)
    summary.observation_passes += 1
    summary.episodes_read += report.episodes_read
    summary.proposals += len(report.proposals)
    summary.discarded_unusable += report.discarded_unusable
    summary.discarded_over_limit += report.discarded_over_limit
    summary.dropped_unsupported += report.dropped_unsupported
    # Read off the ruling the write path returned, never off the deferral queue: the
    # queue is bounded and a refused admission is still an `ASK_USER`, so counting
    # admissions would report an ask rate that falls as the queue fills.
    summary.proposals_deferred += sum(
        1 for proposal in report.proposals if proposal.decision is LearnDecision.DEFERRED
    )
    if report.route is not None:
        summary.observation_routes.add(report.route)
