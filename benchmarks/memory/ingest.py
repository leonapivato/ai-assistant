"""Put one case's conversation through the real capture and distillation path.

**The cadence is interleaved, and that is forced rather than chosen.**
``ObservationStage`` reads *the conversation's most recent ``batch_size`` turns* —
a window, not a cursor, which ADR-0083 §13 records as the reason the scheduler's
observation job ships disabled. Capturing 300 turns and then calling ``observe``
once would distil the last twenty and never see the other 280. So the driver
captures a batch, observes it, captures the next, observes that: the full windows
tile, and the pass count is the honest cost of ingesting that case.

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

**A benchmark turn is not always an exchange.** Capture records one episode per
turn, with a user half and an assistant half. LoCoMo alternates between two named
humans and LongMemEval between a user and an assistant, but neither guarantees strict
alternation — a speaker can take two turns running, and five of LongMemEval's oracle
sessions open on the assistant. So consecutive same-side utterances are joined into
one half, and a session that opens on the assistant side has that run recorded as a
turn of its own with no user half. Neither case is silently smoothed: both are
counted in the summary, because a corpus where they were common would be one whose
ingestion is not saying what a reader assumes.

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
        outcome: The assistant half, or ``None`` where the session ended on the user.
        user_led: Whether ``content`` is genuinely the user's side. ``False`` marks
            the orphan case: an assistant run with no user turn before it, recorded
            in the user half because that is the only half capture requires.
        evidence_keys: The corpus pointers of every turn folded into this exchange,
            in order and without repeats. **Plural because the fold is many-to-one**:
            consecutive same-side utterances join into one half, and the two halves
            are two runs, so one episode can be several cited turns at once. Every
            one of them maps to the single episode this exchange becomes, which is
            the honest resolution — the harness cannot cite half an episode.
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
        assistant_led_turns: Orphan runs — see this module's docstring.
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

    Each exchange carries the evidence keys of **every** turn that went into it, both
    halves included: the fold is many-to-one, so a citation to any of those turns is a
    citation to the one episode they become (#1074).

    Args:
        session: The session.

    Returns:
        The exchanges, in order. Empty for a session with no turns.
    """
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
            windows stop tiling — pass ``settings.observation_batch_size``.

    Returns:
        What it cost and produced.

    Raises:
        ValueError: If ``batch_size`` is not positive, which would make the tiling
            below loop without progress.
    """
    if batch_size < 1:
        msg = f"batch_size must be positive, got {batch_size}"
        raise ValueError(msg)

    # The clock is set before `begin`, because starting a conversation stamps it.
    harness.clock.set(case.sessions[0].occurred_at)
    conversation = await harness.lifecycle.begin(None)
    summary = IngestionSummary(conversation_id=conversation.id)

    pending = 0
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
            pending += 1
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
            if pending == batch_size:
                await _observe(harness, conversation.id, summary)
                pending = 0
    if pending:
        await _observe(harness, conversation.id, summary)
    return summary


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
