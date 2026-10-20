"""The observer's run: the queue, its limits, and the observation record (ADR-0329 §7, §16, §17).

**The trigger is a query** (§7:1, §16:2). An episode is due once it has left the episode
window: once the episode selector the composition root wires into understanding, run as
for the next activation, does not return it (§15:3). The queue is the episodes that are
due, occurred at or after §7:5's instant, have no observation record marked processed,
skipped or stuck, and may be attempted now; it is never a store. An episode that was
attempted stays due whether or not it is back in the window, since it was due once, and
the first time an episode is due is the only time it is processed automatically: a
processed one is never queued again. An open episode, the running activation's own
among them, is not due.

**Ordered, bounded, budgeted, never lossy** (§16:3-§16:9). Due episodes are taken
oldest first, by ``(occurred_at, episode id)``; a run takes at most its bound of them,
and what is left waits for the next run. Before each model call the calls recorded in
the last 24 hours are read through ``PlanStore.observer_calls_since``, and a call that
would exceed the daily budget is not made: the attempt is held and the episode waits,
with nothing dropped, and the run stops. An attempt that fails — a model call, a read,
a write, or a reply that does not parse — is retried after a backoff doubling from a
base to a cap; an episode whose failed attempts reach the stuck count is marked stuck,
kept, and set aside, and later episodes proceed. A held attempt is not a failed one.

**Recorded as it goes** (§16:1, §16:4). The observation record is written after the
scout and after each finding's commit, conditionally on the revision read, with every
model call the attempt made, so the budget counts every call and a retry commits only
the findings with no outcome. A run writes nothing to the episode, links nothing to a
story and adds nothing the selector reads (§7:4).

**What a later attempt needs is on the record, never only in the process** (§12:6,
§16:1, §16:4), so a hub that stops between attempts — or in the middle of one — loses
nothing:

- each pending finding carries its ``supply``, the meet of every record the runs over
  it were supplied, the scout's included: set when the scout proposes it, narrowed by
  every later reading and commit view of its episode before anything is written, and
  read back as the floor a later commit's placement starts from;
- each write a commit lands is put in the finding's ``written`` as soon as it lands,
  before anything else is read or written, so a failure, a cancellation or a stop that
  follows still leaves it on the record; the commit that decides the finding's outcome
  merges them into it and clears ``written`` in the same write, a stuck episode's
  included once an explicit re-run decides it;
- a supersession whose replacement landed is in ``written`` as that replacement's
  create, and a later commit reads again what every memory there was created over
  retired, so a replacement whose retirements were not read when it landed has them
  recorded on the retry.

A pending finding whose ``supply`` is not recorded — one the plan store held before
the field — is proposed again by a new scout over the current reading, since its supply
is unknown and nothing may stand in for it.

**One run at a time** (§16:6): a run asked for while one is running does not start and
answers busy. The hub is one resident process per data directory, so a lock held in
the process is the whole of it; the observation record's conditional write is the
backstop.

**The catch-up is the ordinary run** (§17:1): the first run's queue is every due
episode since §7:5's instant, taken oldest first under the same budget and bound.

**An episode with nothing to read is skipped by rule** (§16:7), with no model call: its
input carries no message, its rounds record no candidate, and its digests hold no
evidence item. An episode with no processing record carries no recorded trigger from
which a support's origin could be set (ADR-0328 §4:2), so it is skipped too.

**It logs stage and code-owned reasons only** (§15:7): counts, states and the names of
the steps, never a fact, a wording, a claim or an identifier that may carry personal
data.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import structlog

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import (
    MemoryStoreError,
    ModelError,
    PlanningError,
    StoryStoreError,
)
from ai_assistant.core.types import (
    EpisodicMemory,
    FindingOutcome,
    FindingUnwritten,
    MemoryOperationKind,
    ObservationAttempt,
    ObservationAttemptEnd,
    ObservationRecord,
    ObservationState,
    ObservationWrite,
    ObserverCall,
    ObserverStep,
    Placement,
)
from ai_assistant.orchestration.observer.commit import (
    CommitReply,
    checked,
    commit_messages,
    commit_view,
)
from ai_assistant.orchestration.observer.reading import EpisodeReader, episode_text
from ai_assistant.orchestration.observer.scout import (
    ScoutReply,
    parsed,
    proposed_findings,
    scout_messages,
)
from ai_assistant.orchestration.observer.writing import FindingWriter, WriteBlocked
from ai_assistant.orchestration.remembering import REMEMBER_CAPABILITY

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import MemoryStore, ModelProvider, PlanStore, StoryStore
    from ai_assistant.core.types import Message, ObservationFinding
    from ai_assistant.orchestration.observer.reading import Reading
    from ai_assistant.orchestration.understanding import EpisodeSelector
    from ai_assistant.orchestration.writes import MemoryWriteStage

__all__ = ["Observer", "ObserverLimits", "RunOutcome"]

_log = structlog.get_logger(__name__)

#: §16:9: the window the daily budget counts calls in.
_A_DAY: Final = timedelta(hours=24)

#: The largest page of episodes the queue reads at once (``MemoryStore.episodes``).
_EPISODE_PAGE: Final = 100


@dataclass(frozen=True, slots=True)
class ObserverLimits:
    """Every bound, budget and instant the observer works within, each the root's to set.

    Attributes:
        since: §7:5's instant: an episode that occurred before it is never due.
        story_episodes: The most recent episodes read per story (§8:1).
        related: The most past episodes, and the most memories, a search reads (§8:1).
        similar: The most similar memories the commit step is shown (§9:3).
        retry_base: The first backoff after a failed attempt (§16:4).
        retry_cap: The longest backoff (§16:4).
        stuck_after: The failed attempts after which an episode is stuck (§16:5).
        per_run: The most episodes one run takes (§16:8).
        daily_calls: The most model calls in any 24 hours (§16:9).
    """

    since: datetime
    story_episodes: int
    related: int
    similar: int
    retry_base: timedelta
    retry_cap: timedelta
    stuck_after: int
    per_run: int
    daily_calls: int

    def __post_init__(self) -> None:
        """Refuse a bound no run could keep.

        Raises:
            ValueError: If ``since`` is naive, a count is below its floor, or a backoff
                is not positive or its cap is below its base.
        """
        if self.since.tzinfo is None or self.since.utcoffset() is None:
            msg = "the observer's instant is timezone-aware (ADR-0329 §7:5)"
            raise ValueError(msg)
        if min(self.story_episodes, self.related, self.similar) < 0:
            msg = "the observer's reading bounds are not negative (ADR-0329 §8:1)"
            raise ValueError(msg)
        if min(self.stuck_after, self.per_run) < 1 or self.daily_calls < 0:
            msg = "the observer's run takes at least one episode and one attempt (§16)"
            raise ValueError(msg)
        if self.retry_base <= timedelta(0) or self.retry_cap < self.retry_base:
            msg = "the observer's backoff doubles from a positive base to a cap (§16:4)"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """What one run did, in counts (§16).

    Attributes:
        busy: Whether it did not start, because a run was already running (§16:6).
        processed: Episodes it processed.
        skipped: Episodes it skipped by rule (§16:7).
        waiting: Episodes it attempted that wait for a retry or the budget.
        stuck: Episodes it marked stuck (§16:5).
        held: Whether the daily budget stopped it (§16:9).
    """

    busy: bool = False
    processed: int = 0
    skipped: int = 0
    waiting: int = 0
    stuck: int = 0
    held: bool = False


class _Held(Exception):  # noqa: N818 — a control-flow signal: the budget, not a failure
    """The daily budget would be exceeded by the next model call (§16:9)."""


class _NotRecorded(Exception):  # noqa: N818 — a control-flow signal: the record, not the attempt
    """The observation record could not be written: another writer, or the store."""


class _Unparsed(Exception):  # noqa: N818 — a control-flow signal with a code-owned name
    """A step's reply did not parse: no proposal, never a partial one."""

    def __init__(self, step: ObserverStep) -> None:
        super().__init__(step.value)
        self.step = step


@dataclass(slots=True)
class _Attempt:
    """One attempt's record as it is built, and the revision it was last written at."""

    record: ObservationRecord
    started_at: datetime
    calls: list[ObserverCall] = field(default_factory=list)


class Observer:
    """The observer: a background stage that commits what a leaving episode shows (§15:1).

    It holds by injection its two model routes, the memory store, the write stage, the
    plan store, the story store and the episode selector (§15:1, §15:3), and every bound
    as :class:`ObserverLimits`. The composition root builds it; nothing here reads a
    setting.
    """

    def __init__(  # noqa: PLR0913 — §15:1 names every collaborator the stage holds
        self,
        *,
        scout: ModelProvider,
        commit: ModelProvider,
        memory: MemoryStore,
        writes: MemoryWriteStage,
        plans: PlanStore,
        stories: StoryStore,
        episodes: EpisodeSelector,
        limits: ObserverLimits,
        now: Callable[[], datetime],
        mint: Callable[[], str] | None = None,
    ) -> None:
        """Wire the observer.

        ``writes`` must write to the ``memory`` store this reads from, and ``episodes``
        must be the selector the composition root wires into understanding, so the
        window it tests is the window understanding is shown (§15:3). The type system
        cannot express either, so both are composition-root obligations.

        Args:
            scout: The scout's model route (§9:1, §9:9).
            commit: The commit step's model route (§9:3, §9:9).
            memory: The memory store episodes and memories are read from.
            writes: The write stage every write goes through (§12:1).
            plans: The plan store observation and effect records are read from and
                written to (§16).
            stories: The story store a story's summary and members are read from (§8:1).
            episodes: ADR-0276 §4's episode selector (§7:1, §15:3).
            limits: Every bound, budget and instant (§§7, 8, 16).
            now: The clock every record, call and write is stamped from.
            mint: Mints the fresh part of a new memory's and question's id; a random
                one where ``None``.
        """
        self._scout = scout
        self._commit = commit
        self._memory = memory
        self._plans = plans
        self._episodes = episodes
        self._limits = limits
        self._now = checked_clock(now, owner="Observer")
        self._mint = mint or _random_id
        self._reader = EpisodeReader(
            memory=memory,
            plans=plans,
            stories=stories,
            story_episodes=limits.story_episodes,
            related=limits.related,
        )
        self._writer = FindingWriter(writes=writes, memory=memory, now=self._now, mint=self._mint)
        self._lock = asyncio.Lock()
        # An outcome decided whose record could not be written, so this process records
        # it as decided rather than committing the finding again. Every write it made is
        # already on the record's ``written``, so a process that no longer holds it
        # decides the finding again with those writes merged in (§12:7, §16:1).
        self._decided: dict[tuple[str, str], ObservationFinding] = {}

    async def run(self) -> RunOutcome:
        """One run over the queue, unless a run is already running (§16:6).

        Returns:
            What the run did. Nobody waits on a run, and a failure in one episode is
            that episode's attempt, never the run's.

        Raises:
            MemoryStoreError: If the queue cannot be read.
            PlanningError: If the queue's observation records cannot be read.
        """
        if self._lock.locked():
            _log.info("observer_run", stage="run", result="busy")
            return RunOutcome(busy=True)
        async with self._lock:
            outcome = await self._run()
        _log.info(
            "observer_run",
            stage="run",
            result="held" if outcome.held else "done",
            processed=outcome.processed,
            skipped=outcome.skipped,
            waiting=outcome.waiting,
            stuck=outcome.stuck,
        )
        return outcome

    async def _run(self) -> RunOutcome:
        window = await self._episodes(frozenset())
        queue = await self.due(window)
        outcome = RunOutcome()
        for episode, held in queue[: self._limits.per_run]:
            try:
                state = await self._attempted(episode, held, window)
            except _Held:
                return replace(outcome, waiting=outcome.waiting + 1, held=True)
            except _NotRecorded:
                # The record could not be written: another writer moved it (§16:6's
                # backstop) or the store failed. Nothing more is attempted this run.
                _log.info("observer_run", stage="record", result="not_written")
                return outcome
            outcome = _counted(outcome, state)
        return outcome

    async def due(
        self, window: Sequence[EpisodicMemory]
    ) -> list[tuple[str, ObservationRecord | None]]:
        """The queue: the episodes due now, oldest first, each with its record (§16:2).

        Args:
            window: The episodes the selector returns, run as for the next activation.

        Returns:
            Each due episode's id, and its observation record where it has one.

        Raises:
            MemoryStoreError: If the episodes cannot be enumerated.
            PlanningError: If their observation records cannot be read.
        """
        now = self._now()
        in_window = {one.id for one in window}
        rows: list[tuple[datetime, str]] = []
        cursor: str | None = None
        while True:
            page = await self._memory.episodes(cursor=cursor, limit=_EPISODE_PAGE)
            ended = False
            for row in page.items:
                position = row.position
                if position.occurred_at < self._limits.since:
                    ended = True
                    break
                if row.has_processing_record and row.status is None:
                    continue  # open: still running, never due (ADR-0286 §6:4)
                rows.append((position.occurred_at, position.episode_id))
            if ended or page.next_cursor is None or page.next_cursor == cursor:
                break
            cursor = page.next_cursor
        records = {one.episode: one for one in await self._plans.observations([i for _, i in rows])}
        queue: list[tuple[datetime, str, ObservationRecord | None]] = []
        for occurred_at, episode in rows:
            held = records.get(episode)
            if (held is None and episode not in in_window) or (
                held is not None and held.attemptable(now)
            ):
                queue.append((occurred_at, episode, held))
        queue.sort(key=lambda one: (one[0], one[1]))
        return [(episode, held) for _, episode, held in queue]

    async def _attempted(
        self, episode_id: str, held: ObservationRecord | None, window: Sequence[EpisodicMemory]
    ) -> ObservationState | None:
        """One attempt at one episode, recorded as it goes; its state, or ``None`` if gone."""
        started = self._now()
        try:
            episode = await self._memory.get(episode_id)
        except MemoryStoreError as exc:
            # A read that fails is the attempt's failure, recorded and backed off (§16:4).
            return await self._failed(await self._open(episode_id, held, started), exc)
        if not isinstance(episode, EpisodicMemory):
            return None  # deleted since it was queued: nothing left to read
        if _nothing_to_read(episode) and (
            held is None or (held.call_count() == 0 and not held.findings)
        ):
            # §16:7, after any earlier attempt that failed before reading anything.
            skipped = ObservationRecord(
                episode=episode_id,
                state=ObservationState.SKIPPED,
                attempts=(
                    *(() if held is None else _closed(held.attempts)),
                    ObservationAttempt(started_at=started, end=ObservationAttemptEnd.FINISHED),
                ),
            )
            await self._record(skipped, expected_revision=0 if held is None else held.revision)
            return ObservationState.SKIPPED
        attempt = await self._open(episode_id, held, started)
        try:
            await self._processed(episode, attempt, window)
        except _Held:
            await self._close(attempt, ObservationAttemptEnd.HELD, ObservationState.WAITING)
            raise
        except (
            ModelError,
            MemoryStoreError,
            StoryStoreError,
            PlanningError,
            WriteBlocked,
            _Unparsed,
        ) as exc:
            return await self._failed(attempt, exc)
        await self._close(attempt, ObservationAttemptEnd.FINISHED, ObservationState.PROCESSED)
        self._forget(episode_id)
        return ObservationState.PROCESSED

    def _forget(self, episode_id: str) -> None:
        """Drop the outcomes this process kept beside an episode processed or read afresh."""
        for key in [key for key in self._decided if key[0] == episode_id]:
            del self._decided[key]

    async def _open(
        self, episode_id: str, held: ObservationRecord | None, started: datetime
    ) -> _Attempt:
        """Start an attempt: the episode waits, its attempt open, recorded (§16:1)."""
        attempts = () if held is None else _closed(held.attempts)
        record = ObservationRecord(
            episode=episode_id,
            state=ObservationState.WAITING,
            attempts=(*attempts, ObservationAttempt(started_at=started)),
            findings=() if held is None else held.findings,
        )
        stored = await self._record(record, expected_revision=0 if held is None else held.revision)
        return _Attempt(record=stored, started_at=started)

    async def _processed(
        self, episode: EpisodicMemory, attempt: _Attempt, window: Sequence[EpisodicMemory]
    ) -> None:
        """Read, scout where no finding is pending yet, and commit each finding left.

        The findings an earlier attempt proposed are committed over the supply recorded
        on each, narrowed by this attempt's reading (§12:6). A pending finding whose
        supply is not recorded is proposed again over this attempt's reading, and those
        with an outcome stay as recorded (§16:4).
        """
        reading = await self._reader.read(episode, window)
        findings = attempt.record.findings
        unknown = any(one.outcome is None and one.supply is None for one in findings)
        if not findings or unknown:
            kept = tuple(one for one in findings if one.outcome is not None)
            self._forget(episode.id)
            await self._scouted(reading, attempt, kept)
        else:
            _narrow(attempt, reading.supplied)
        for finding_id in [one.id for one in attempt.record.findings if one.outcome is None]:
            key = (episode.id, finding_id)
            # An outcome decided before its record failed to be written is recorded as
            # decided, never committed again over writes that already landed (§16:1).
            outcome = self._decided.get(key) or await self._committed(finding_id, reading, attempt)
            self._decided[key] = outcome
            done = tuple(
                outcome if one.id == finding_id else one for one in attempt.record.findings
            )
            await self._save(attempt, findings=done)
            del self._decided[key]

    async def _scouted(
        self, reading: Reading, attempt: _Attempt, kept: tuple[ObservationFinding, ...]
    ) -> None:
        """The scout's one call, and its findings recorded after those kept (§9:1-§9:2).

        Each new finding carries the meet of what the scout was supplied (§12:6), so a
        commit in a later attempt, by this process or after a restart, starts from it.
        """
        reply = await self._call(attempt, ObserverStep.SCOUT, self._scout, scout_messages(reading))
        proposal = parsed(reply, ScoutReply)
        if proposal is None:
            raise _Unparsed(ObserverStep.SCOUT)
        findings, dropped = proposed_findings(proposal, reading, numbered_from=_next_number(kept))
        supply = Placement.narrowest_of(reading.supplied)
        _log.info("observer_scout", stage="scout", findings=len(findings), dropped=dropped)
        await self._save(
            attempt, findings=(*kept, *(_updated(one, supply=supply) for one in findings))
        )

    async def _committed(
        self, finding_id: str, reading: Reading, attempt: _Attempt
    ) -> ObservationFinding:
        """One finding's commit call, code's checks, and its writes (§9:3-§9:5, §12).

        What an earlier commit of the finding wrote — its ``written``, with what any
        replacement there retired read again — joins the outcome, whatever this one
        decides, and the outcome clears ``written`` in the write that records it (§16:1).
        """
        finding = _finding(attempt, finding_id)
        earlier = await self._recovered(finding.written)
        if earlier != finding.written:
            _set(attempt, _updated(finding, written=earlier))
        outcome = await self._decision(finding_id, reading, attempt, earlier)
        if earlier:
            outcome = _with_writes(outcome, earlier)
        _log.info(
            "observer_commit",
            stage="commit",
            ruling=None if outcome.ruling is None else outcome.ruling.value,
            unwritten=None if outcome.unwritten is None else outcome.unwritten.value,
            writes=len(outcome.writes),
        )
        return _updated(_finding(attempt, finding_id), written=(), outcome=outcome)

    async def _recovered(
        self, written: tuple[ObservationWrite, ...]
    ) -> tuple[ObservationWrite, ...]:
        """``written``, with the end on each memory a replacement there retired (§16:1).

        A supersession lands whole, so what it retired is on its replacement's create
        however the replacement stands now. A memory ``written`` already names — the
        retirement read when it landed, or the one a proposal's own retiring operation
        made — is not named again.

        Raises:
            MemoryStoreError: Where a replacement cannot be read: the attempt fails,
                ``written`` stays as recorded, and the retry reads it again.
        """
        created = [one.memory for one in written if MemoryOperationKind.CREATE in one.operations]
        if not created:
            return written
        named = {one.memory for one in written}
        ends = await self._writer.retirements(created)
        return _joined(written, [one for one in ends if one.memory not in named])

    async def _decision(
        self,
        finding_id: str,
        reading: Reading,
        attempt: _Attempt,
        earlier: tuple[ObservationWrite, ...],
    ) -> FindingOutcome:
        """This commit's call, checks and writes: what it wrote, or why nothing was.

        Every write that lands is put in the finding's ``written`` beside ``earlier``
        and saved before the next is made (§16:1).
        """
        view = await commit_view(
            _finding(attempt, finding_id),
            reading,
            reader=self._reader,
            memory=self._memory,
            plans=self._plans,
            similar=self._limits.similar,
        )
        if view is None:
            return _check_failed(self._now())
        _narrow(attempt, view.supplied)
        supply = _finding(attempt, finding_id).supply
        reply = await self._call(attempt, ObserverStep.COMMIT, self._commit, commit_messages(view))
        decision = parsed(reply, CommitReply)
        if decision is None:
            raise _Unparsed(ObserverStep.COMMIT)
        verdict = checked(
            decision,
            view,
            now=self._now(),
            mint=self._mint,
            placement=Placement() if supply is None else supply,
        )

        async def landed(writes: tuple[ObservationWrite, ...]) -> None:
            current = _finding(attempt, finding_id)
            _set(attempt, _updated(current, written=_joined(earlier, writes)))
            await self._save(attempt, findings=attempt.record.findings)

        return await self._writer.write(
            verdict, shown=[one.memory for one in view.similar], landed=landed
        )

    async def _call(
        self,
        attempt: _Attempt,
        step: ObserverStep,
        route: ModelProvider,
        messages: list[Message],
    ) -> str:
        """One model call, inside the daily budget (§16:9), recorded on the attempt."""
        at = self._now()
        made = await self._plans.observer_calls_since(at - _A_DAY)
        if made >= self._limits.daily_calls:
            raise _Held
        attempt.calls.append(ObserverCall(step=step, at=at))
        # Recorded before the call is made, so a call cancelled or lost with the process
        # mid-flight still counts against the budget (§16:9).
        await self._save(attempt, findings=attempt.record.findings)
        reply = await route.complete(messages)
        return reply.content

    async def _save(self, attempt: _Attempt, *, findings: tuple[ObservationFinding, ...]) -> None:
        """Write the record with the findings and the calls so far, the attempt still open."""
        record = _with_attempt(attempt, findings=findings, end=None, state=ObservationState.WAITING)
        attempt.record = await self._record(record, expected_revision=attempt.record.revision)

    async def _close(
        self, attempt: _Attempt, end: ObservationAttemptEnd, state: ObservationState
    ) -> None:
        record = _with_attempt(attempt, findings=attempt.record.findings, end=end, state=state)
        attempt.record = await self._record(record, expected_revision=attempt.record.revision)

    async def _record(
        self, record: ObservationRecord, *, expected_revision: int
    ) -> ObservationRecord:
        """Write the observation record, conditionally (§16:1, §16:6).

        Raises:
            _NotRecorded: Where the plan store refused or failed the write.
        """
        try:
            return await self._plans.write_observation(record, expected_revision=expected_revision)
        except PlanningError as exc:
            raise _NotRecorded from exc

    async def _failed(self, attempt: _Attempt, exc: Exception) -> ObservationState:
        """§16:4-§16:5: a backoff, or stuck once the failed attempts reach the count."""
        failures = 1 + sum(
            1 for one in attempt.record.attempts[:-1] if one.end is ObservationAttemptEnd.FAILED
        )
        stuck = failures >= self._limits.stuck_after
        state = ObservationState.STUCK if stuck else ObservationState.WAITING
        record = _with_attempt(
            attempt,
            findings=attempt.record.findings,
            end=ObservationAttemptEnd.FAILED,
            state=state,
        )
        if not stuck:
            backoff = self._limits.retry_base
            for _ in range(failures - 1):  # doubled to the cap, never past it (§16:4)
                backoff = min(self._limits.retry_cap, backoff * 2)
            record = ObservationRecord.model_validate(
                {**record.model_dump(), "next_attempt_at": self._now() + backoff}
            )
        attempt.record = await self._record(record, expected_revision=attempt.record.revision)
        _log.info(
            "observer_attempt",
            stage=exc.step.value if isinstance(exc, _Unparsed) else "attempt",
            result=state.value,
            reason=_reason(exc),
            failures=failures,
        )
        return state


def _updated(finding: ObservationFinding, **fields: object) -> ObservationFinding:
    """``finding`` with ``fields`` replaced, validated whole (§16:1)."""
    return type(finding).model_validate({**dict(finding), **fields})


def _finding(attempt: _Attempt, finding_id: str) -> ObservationFinding:
    """The finding ``finding_id`` as the attempt's record now holds it."""
    return next(one for one in attempt.record.findings if one.id == finding_id)


def _set(attempt: _Attempt, finding: ObservationFinding) -> None:
    """Put ``finding`` on the attempt's record in place of its earlier self, unsaved.

    The next write of the record — a model call's, a landed write's, the outcome's or
    the failure's — carries it.
    """
    findings = tuple(finding if one.id == finding.id else one for one in attempt.record.findings)
    attempt.record = attempt.record.model_copy(update={"findings": findings})


def _narrow(attempt: _Attempt, supplied: Sequence[Placement]) -> None:
    """Narrow every pending finding's supply by ``supplied`` (§12:6), unsaved.

    Every record the run reads over an episode is supplied to it, so each finding still
    to be committed takes the meet, whichever finding's commit view read it; a finding
    whose supply is unknown stays unknown.
    """
    if not supplied:
        return
    for one in attempt.record.findings:
        if one.outcome is None and one.supply is not None:
            _set(attempt, _updated(one, supply=Placement.narrowest_of([one.supply, *supplied])))


def _reason(exc: Exception) -> str:
    """A failed attempt's code-owned reason: never an error's message (§15:7)."""
    if isinstance(exc, _Unparsed):
        return "unparsed"
    if isinstance(exc, WriteBlocked):
        return "placement"
    return type(exc).__name__


def _next_number(findings: Sequence[ObservationFinding]) -> int:
    """The number the next finding's id takes, past every id on the record (``f1``...)."""
    numbers = [int(one.id[1:]) for one in findings if one.id[1:].isdigit()]
    return max(numbers, default=0) + 1


def _joined(
    earlier: Sequence[ObservationWrite], later: Sequence[ObservationWrite]
) -> tuple[ObservationWrite, ...]:
    """Two runs of writes as one, each memory once, its operations in the order written."""
    operations: dict[str, list[MemoryOperationKind]] = {}
    entries: dict[str, bool | None] = {}
    for write in (*earlier, *later):
        operations.setdefault(write.memory, []).extend(write.operations)
        if write.track_record is not None or write.memory not in entries:
            entries[write.memory] = write.track_record
    return tuple(
        ObservationWrite(memory=memory, operations=tuple(kinds), track_record=entries[memory])
        for memory, kinds in operations.items()
    )


def _with_writes(outcome: FindingOutcome, earlier: Sequence[ObservationWrite]) -> FindingOutcome:
    """``outcome`` with what an earlier, failed commit of the same finding wrote (§16:1)."""
    return FindingOutcome(
        at=outcome.at, ruling=outcome.ruling, writes=_joined(earlier, outcome.writes)
    )


def _random_id() -> str:
    return uuid4().hex


def _closed(attempts: Sequence[ObservationAttempt]) -> tuple[ObservationAttempt, ...]:
    """Earlier attempts, a last one left open by a crash closed as failed (§16:1)."""
    return tuple(
        one if one.end is not None else one.model_copy(update={"end": ObservationAttemptEnd.FAILED})
        for one in attempts
    )


def _with_attempt(
    attempt: _Attempt,
    *,
    findings: tuple[ObservationFinding, ...],
    end: ObservationAttemptEnd | None,
    state: ObservationState,
) -> ObservationRecord:
    """The record with this attempt's calls and end, the findings and the state given."""
    current = ObservationAttempt(started_at=attempt.started_at, calls=tuple(attempt.calls), end=end)
    return ObservationRecord(
        episode=attempt.record.episode,
        state=state,
        attempts=(*attempt.record.attempts[:-1], current),
        findings=findings,
    )


def _check_failed(at: datetime) -> FindingOutcome:
    return FindingOutcome(at=at, unwritten=FindingUnwritten.CHECK_FAILED)


def _nothing_to_read(episode: EpisodicMemory) -> bool:
    """§16:7: no message in the input, no candidate in the rounds, no evidence item."""
    processing = episode.processing_record
    if processing is None:
        return True
    if episode_text(episode).strip():
        return False
    if any(call.name == REMEMBER_CAPABILITY for one in processing.rounds for call in one.calls):
        return False
    return not any(digest.evidence for digest in processing.digests)


def _counted(outcome: RunOutcome, state: ObservationState | None) -> RunOutcome:
    match state:
        case ObservationState.PROCESSED:
            return replace(outcome, processed=outcome.processed + 1)
        case ObservationState.SKIPPED:
            return replace(outcome, skipped=outcome.skipped + 1)
        case ObservationState.STUCK:
            return replace(outcome, stuck=outcome.stuck + 1)
        case ObservationState.WAITING:
            return replace(outcome, waiting=outcome.waiting + 1)
        case _:
            return outcome
