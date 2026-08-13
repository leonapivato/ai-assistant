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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from benchmarks.memory.cases import BenchCase, BenchSession
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
    """

    content: str
    outcome: str | None
    user_led: bool


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
        observation_routes: Every model route that read episodes. More than one means
            the configuration moved mid-run, which invalidates the case.
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
    observation_routes: set[str] = field(default_factory=set)

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


def exchanges_of(session: BenchSession) -> tuple[Exchange, ...]:
    """Fold a session's utterances into the exchanges capture records.

    Args:
        session: The session.

    Returns:
        The exchanges, in order. Empty for a session with no turns.
    """
    runs: list[tuple[bool, list[str]]] = []
    for turn in session.turns:
        if runs and runs[-1][0] == turn.user_side:
            runs[-1][1].append(turn.text)
        else:
            runs.append((turn.user_side, [turn.text]))

    built: list[Exchange] = []
    index = 0
    while index < len(runs):
        user_side, texts = runs[index]
        joined = "\n".join(texts)
        if not user_side:
            # An assistant run with nothing before it. Recorded rather than dropped:
            # LongMemEval's assistant turns carry evidence (#1029's P6), and losing
            # them would answer P6 by construction instead of by measurement.
            built.append(Exchange(content=joined, outcome=None, user_led=False))
            index += 1
            continue
        following = runs[index + 1] if index + 1 < len(runs) else None
        outcome = "\n".join(following[1]) if following is not None else None
        built.append(Exchange(content=joined, outcome=outcome, user_led=True))
        index += 2 if following is not None else 1
    return tuple(built)


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
            if report.degraded or report.episode_id is None:
                summary.turns_degraded += 1
                continue
            summary.turns_captured += 1
            if not exchange.user_led:
                summary.assistant_led_turns += 1
            pending += 1
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
    if report.route is not None:
        summary.observation_routes.add(report.route)
