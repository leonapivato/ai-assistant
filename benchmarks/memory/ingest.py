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
whose episode no longer resolves (ADR-0074 §5). So the driver schedules on the store's
own ``ConversationTurn.ordinal`` rather than on its capture count — the one exact
answer to where a turn sits, and the one thing ``CaptureReport`` cannot give it
(#1075) — and fires the next pass when the window would *begin* at the current
window's *k*-th episode from the end. That delivers the clause with a gap in the
window, with an append that never landed, or with neither. The loss it closes is a
fact stated across a window boundary — the
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

from collections import deque
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

    # **The schedule is kept in store-allocated turn ordinals, and the overlap is
    # measured in episodes.** ADR-0162 §7's clause is about episodes — "the last *k*
    # episodes of one window are the first *k* of the next" — while
    # ``ObservationStage``'s window is the conversation's most recent ``batch_size``
    # **turns**, and it skips a turn whose episode no longer resolves without
    # backfilling (ADR-0074 §5). The two sequences are not the same one, so a driver
    # pacing on its own capture count delivers §7 only while nothing fails.
    #
    # So the driver reads the conversation's own ordinal after every capture and
    # schedules on that. ``ConversationTurn.ordinal`` is allocated by the store, dense
    # and monotonic within its conversation (ADR-0074 §3), which makes it the one
    # exact answer to "where is this turn in the window" — and the one thing
    # ``CaptureReport`` cannot supply, because it reports a lost **append** and a lost
    # **episode** identically (#1075, whose title says in terms that a driver's cadence
    # needs the distinction). An unappended turn does not move the ordinal and an
    # unresolvable one does, which is exactly the distinction the schedule needs, taken
    # from the store rather than guessed from the report. One row per capture, against
    # a model call per pass.
    #
    # After a pass over the turns ending at ``through``, :func:`_next_pass_at` takes
    # that window's episode-bearing ordinals, picks the ``overlap``-th from the end,
    # and fires the next pass when the window would *begin* there — which makes exactly
    # those ``overlap`` episodes the next window's prefix, gap or no gap.
    #
    # **A capture that stored nothing buys no pass of its own.** A window whose new
    # turns all failed their episode write reads a strict subset of what the last pass
    # read: a duplicate model call, on a paid run, proposing what the gate will fold.
    # So the trigger also asks whether an episode has landed since the last pass, keyed
    # on the episode id alone rather than on ``degraded`` — the conservative direction,
    # because a report that is degraded and still carries an id has something to read.
    #
    # **That gate postpones a pass and never cancels one**, which is why the ordinal
    # test is ``>=`` and not ``==``: postponing can carry the conversation past the
    # scheduled ordinal, and the pass then fires on the first capture that lands. What
    # a long postponement can cost is the carried tail's *position* — the window slides
    # while nothing is stored — and that costs §7 nothing, because a stretch that stored
    # nothing has no new fact for the tail to be joined to.
    # Pruned to the current window by :func:`_record_landing`, so the schedule costs
    # the same on turn one and turn a million.
    landed: deque[int] = deque()
    observed_through = 0
    next_at: int | None = None
    for session in case.sessions:
        harness.clock.set(session.occurred_at)
        for exchange in exchanges_of(session):
            report = await harness.lifecycle.capture(
                conversation.id, content=exchange.content, outcome=exchange.outcome
            )
            # **Read before it is classified, because the window is turns and this
            # loop cannot see from the report which kind of degradation it got.**
            # `capture` writes the index entry first and the episode second, so an
            # episode-stage failure leaves a turn in the conversation carrying an id
            # that no longer resolves; `ObservationStage` reads the most recent
            # `batch_size` *turns* and skips an unresolvable one **without
            # backfilling** (ADR-0074 §5), so that turn still holds a slot. A lost
            # append records no turn and holds none. The store's own ordinal is what
            # separates them, and it is why this is read rather than counted.
            ordinal = await _tail_ordinal(harness, conversation.id)
            next_at = ordinal + batch_size - 1 if next_at is None and ordinal else next_at
            # Recorded off the episode id alone rather than off the branch below,
            # which is the conservative direction: a report that is `degraded` and
            # still carries an id has something a pass can read.
            _record_landing(landed, ordinal, stored=report.episode_id is not None, reach=batch_size)
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
            if _pass_is_due(ordinal=ordinal, next_at=next_at, observed_through=observed_through):
                await _observe(harness, conversation.id, summary)
                next_at = _next_pass_at(
                    landed, through=ordinal, batch_size=batch_size, overlap=overlap
                )
                observed_through = ordinal
    if landed and landed[-1] > observed_through:
        await _observe(harness, conversation.id, summary)
    return summary


def _record_landing(landed: deque[int], ordinal: int, *, stored: bool, reach: int) -> None:
    """Note an episode at ``ordinal``, and forget the ones out of reach.

    Args:
        landed: The ordinals still inside a window the driver could schedule from.
            Mutated in place.
        ordinal: The conversation's most recent turn ordinal.
        stored: Whether that turn stored an episode.
        reach: The window, in turns — how far back an ordinal can be and still matter.

    An ordinal that has fallen out of reach can never return: ``ObservationStage`` has
    no offset, so it never reads a window starting further back than the most recent
    ``reach`` turns. Keeping the whole history would make the scheduling quadratic in a
    corpus's successful turns for no answer it could give.
    """
    if stored:
        landed.append(ordinal)
    while landed and landed[0] <= ordinal - reach:
        landed.popleft()


def _pass_is_due(*, ordinal: int, next_at: int | None, observed_through: int) -> bool:
    """Whether the conversation has reached the scheduled window and has moved.

    Two conditions and both are load-bearing, and neither of them is "an episode
    landed". The conversation's most recent turn is at or past the ordinal
    :func:`_next_pass_at` named, so the window begins where ADR-0162 §7 asks; and the
    conversation has advanced since the last pass, so this is not the identical window
    read twice.

    **A due pass is never deferred for want of a new episode**, which is the
    difference between this and a gate on ``landed``. A stretch of episode-write
    failures still moves the conversation, so deferring past the due ordinal would let
    the window slide off the carried tail — the boundary §7 exists to preserve — to
    save a pass. §7 admits one exception and it is not that one. The pass such a
    stretch buys reads a window with gaps in it and no new episode, which is a wasted
    call and is the price of the boundary.

    **What the second condition rules out is the window that has not moved at all.** A
    lost append records no turn, so the ordinal stands still; without this the driver
    would re-read one window on every subsequent capture. It is stated on the ordinal
    rather than on ``landed`` because it is the *window* that must differ, and a
    window that slid holds different evidence whether or not any of it is new.

    Args:
        ordinal: The conversation's most recent turn ordinal, 0 where it has none.
        next_at: The scheduled ordinal, or ``None`` before the first turn lands.
        observed_through: The ordinal the last pass read through, 0 before any.

    Returns:
        Whether to observe now.
    """
    if next_at is None or ordinal < next_at:
        return False
    return ordinal > observed_through


async def _tail_ordinal(harness: Harness, conversation_id: str) -> int:
    """The ordinal of the conversation's most recent turn, or 0 where it has none.

    The one exact answer to "did that capture put a turn in the conversation, and
    where". ``ConversationTurn.ordinal`` is store-allocated, dense and monotonic
    within its conversation (ADR-0074 §3), so a lost append leaves it where it was and
    an episode-stage failure advances it — the distinction ``CaptureReport`` cannot
    make (#1075) and this driver's schedule needs. Read through the ratified
    ``ConversationStore.turns`` contract, one row, and never derived from an episode
    id: an id is opaque and a driver reading a position out of one would be inventing
    a second id space beside the store's own.

    Args:
        harness: The wired pipeline, whose conversation store this reads.
        conversation_id: The conversation.

    Returns:
        The last ordinal, or 0 for a conversation with no turns yet — below
        ``FIRST_TURN_ORDINAL`` by construction, so it can never be mistaken for one.
    """
    tail = await harness.conversations.turns(conversation_id, limit=1)
    return tail[-1].ordinal if tail else 0


def _next_pass_at(landed: Sequence[int], *, through: int, batch_size: int, overlap: int) -> int:
    """The ordinal at which the next pass's window begins where §7 asks.

    A pass has just read the turns ``[through - batch_size + 1, through]``, in
    ordinals. ADR-0162 §7 requires the last ``overlap`` **episodes** of that window to
    be the first ``overlap`` of the next, so the next window must *begin* at the
    ordinal of this window's ``overlap``-th episode from the end — and a window of
    ``batch_size`` turns beginning there ends ``batch_size - 1`` later, which is the
    answer.

    Args:
        landed: The ordinal of every turn that stored an episode, in order.
        through: The last ordinal the pass just read.
        batch_size: The window, in turns.
        overlap: §7's *k*, already clamped into its bound by :func:`_overlap_of`.

    Returns:
        The ordinal at which the next pass is due.

    **A window holding no more episodes than the carry is outside the clause's
    protasis, and that is the text rather than an exception to it.** §7 binds "where
    consecutive observation passes **tile a sequence of episodes rather than re-reading
    one window**". Where the gaps in a window leave it with *k* episodes or fewer, the
    only start that makes its last *k* episodes the next window's prefix is the start
    it already has — so the identity there *is* re-reading one window, which is the
    case the clause's own opening words exclude rather than govern. §7 says the same
    thing in its own voice one clause later, of the one-turn window: "no value
    satisfies progress and overlap together — a property of a one-turn window rather
    than something this section can repair". A window whose episodes are down to the
    carry has acquired that property, and this section cannot repair it either.

    So the start is floored at one turn past this window's: the least advance there is,
    carrying the most the window has left to give, and never a step that stands still.
    It is reachable only after ``batch_size - overlap`` episode-write failures inside
    one window, which is a store failing repeatedly and is counted as
    :attr:`IngestionSummary.turns_degraded` where a reader will see it.

    An ``overlap`` of 0 is §7's explicit exception, the batch of 1, and a window that
    held no episode at all has nothing to aim at; both fall back to the next
    non-overlapping window.
    """
    if overlap == 0:
        return through + batch_size
    window = [position for position in landed if position > through - batch_size]
    if not window:
        return through + batch_size
    aimed = window[max(0, len(window) - overlap)]
    return max(aimed, through - batch_size + 2) + batch_size - 1


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
