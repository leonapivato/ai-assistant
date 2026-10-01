"""Put one case's conversation through the real capture and distillation path.

**Not runnable since ADR-0283** (#2626). The driver captured through
``ConversationLifecycle.capture`` and kept its cadence in turn ordinals, and both
were retired with the turn index: a conversation's history is now its episodes,
and an episode is on a conversation's channel only through its processing record.
:func:`ingest_case` raises ``NotImplementedError`` until #2626 ports it onto that
path. The description below is the driver as it stood, kept for that port.

**The cadence is interleaved, and that is forced rather than chosen.** An
observation pass reads *the turns above the conversation's durable observation
watermark* (ADR-0212 §3), and a conversation that has never been observed starts at
its **tail** window rather than at its first turn (§4). So capturing 300 turns and
then calling ``observe`` would distil the last ``batch_size`` of them, stamp the
watermark at the end of the conversation, and pass over the other 280 permanently.
The driver therefore captures a batch, observes it, captures the next, observes
that: the pages tile from the conversation's first turn onward, and the pass count
is the honest cost of ingesting that case.

**Consecutive pages tile contiguously and share nothing** (ADR-0220 §1). ADR-0162
§7 required the last *k* **episodes** of one window to be the first *k* of the next;
ADR-0212 §1 rules that no later pass of a build reading the watermark selects a turn
at or below it, so an overlap is exactly the re-selection it forbids. ADR-0220 §1
rules ADR-0212's clauses the ones that stand, forgoes §7's overlap for this walk and
sets *k* to 0 there. This driver therefore **computes no overlap, defers no pass to
place a carried tail, and creates no re-observation of its own** (ADR-0220 §3): it
only chooses *when* to call the stage, and the stage's page is fixed by the
watermark, so no schedule a driver can perform makes two pages share an episode.

**What that gives up is accepted rather than mitigated** (ADR-0220 §2). A fact
stated across a page boundary — the user names a trip in the last turn of one page
and says where they went in the first turn of the next — is visible to neither pass
as a whole, at a rate set by the alignment of the pages rather than by the data.
Nothing here mitigates it and nothing measures it. A benchmark run made after this
change is therefore **not comparable on ingestion** to one made before it: pilot-5's
figures were produced with the overlap in force, so a comparison across the change
needs the earlier arm re-run rather than adjusted (ADR-0220 §3).

**The schedule is kept in store-allocated turn ordinals, and never in captures.** A
pass is due once the conversation holds ``batch_size`` turns **above its
watermark** — one full page in ADR-0212 §3's sense, which is a bound in *turns* and
never in captures. The two sequences are not the same one: a lost **append** stores
no turn and moves no ordinal, while a lost **episode** leaves a turn in the
conversation that the stage passes over without backfilling (ADR-0074 §5), and
``CaptureReport`` reports the two identically (#1075, whose title says in terms that
a driver's cadence needs the distinction). So the driver reads the conversation's own
tail ordinal and its own watermark from the store rather than counting its successes;
a cadence in captures would disagree with the store the first time an append failed,
and would fire a short page against a ``Settings`` bound that counts turns.

**The closing flush stays, and the cadence above does not replace it** (ADR-0220
§3). When a case's captures are exhausted and its conversation still holds turns
above its watermark, the driver keeps passing until it holds none. A case whose turn
count is not a multiple of the batch is an ordinary input, and a case shorter than
one batch outright is the commonest one: a LongMemEval haystack often is, so skipping
the closing pass would ingest a conversation and distil nothing from it. What the
flush *costs* changed with the watermark — against a tail read the closing pass
re-read ``batch_size - remainder`` turns an earlier pass had already distilled, and
against the watermark it reads only turns above it, bounded like every other page, so
it re-reads nothing. **The loop is over passes that return**: a pass that raises is
not retried inside it, the flush stops there and the raise surfaces, leaving the
watermark wherever ADR-0212 §6 leaves it. It terminates on ADR-0212 §5's guarantee
that the watermark never stands still across a pass over a non-empty page, which
reaches every pass it makes.

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
from typing import TYPE_CHECKING

from ai_assistant.core.types import LearnDecision

if TYPE_CHECKING:
    from collections.abc import Sequence

    from benchmarks.memory.cases import BenchCase, BenchSession, BenchTurn
    from benchmarks.memory.wiring import Harness

__all__ = ["Exchange", "IngestionSummary", "exchanges_of", "ingest_case"]


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
        """Episodes read beyond the turns capture stored — a proxy, not a tally.

        **This driver no longer produces a re-observation of its own, and the value
        is left exactly as it is** (ADR-0220 §3). Passes run serially over
        contiguous, disjoint pages, so no page holds an episode an earlier page held;
        and a turn ADR-0212 §5 leaves for a later page was never handed to the
        observer, so reading it later shows it once.

        What survives is the expression, and it is a difference between two counters
        incremented on **different tests** rather than a count of episodes some pass
        read twice: a capture is counted under :attr:`turns_degraded` whenever it is
        ``degraded`` *or* carries no episode id, while its landing is recorded off the
        episode id alone. ADR-0220 §3 rules nothing about what that difference
        computes, and **#1837** records the discrepancy — closing it is a rename or a
        true per-episode metric, and this is neither.

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
    """Capture a case's conversation and distil it — not runnable since ADR-0283.

    ADR-0283 retired what this driver stood on: ``ConversationLifecycle.capture``,
    which wrote an episode on no conversation's channel, and the turn ordinals its
    cadence and closing flush counted. Porting it onto the activation writer's path
    is #2626; until then it refuses rather than ingesting nothing, so a run cannot
    report an empty ingestion as a measured one.

    Args:
        harness: The wired pipeline.
        case: The case to ingest.
        batch_size: The observation page size.

    Raises:
        NotImplementedError: Always, citing #2626.
    """
    del harness, case, batch_size
    msg = "benchmark ingestion is not ported off the retired turn index (#2626, ADR-0283)"
    raise NotImplementedError(msg)


async def _observe(harness: Harness, conversation_id: str, summary: IngestionSummary) -> None:
    """Run one observation pass and fold its report into ``summary``.

    Args:
        harness: The wired pipeline.
        conversation_id: The conversation to observe. Passed explicitly rather than
            letting the stage select the first candidate by least recent activity
            (ADR-0212 §3), because selection reads the conversation index and this
            driver already knows the answer — and because a case must be ingested
            into its own conversation, not into whichever one the walk would reach.
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
