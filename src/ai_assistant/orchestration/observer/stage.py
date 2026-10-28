"""The observer's run: the queue, its limits, and the observation record (ADR-0329 §7, §16).

**The trigger is a query** (ADR-0329 §7:1, §16:2). An episode is due once it has left the
episode window: once the episode selector the composition root wires into understanding,
run as for the next activation, does not return it (§15:3). The queue is the episodes
that are due, occurred at or after §7:5's instant, have no observation record marked
processed, skipped or stuck, and may be attempted now; it is never a store. An episode
that was attempted stays due whether or not it is back in the window, since it was due
once, and the first time an episode is due is the only time it is processed
automatically. An open episode, the running activation's own among them, is not due.

**One episode, its steps** (ADR-0346 §2-§6). Each attempt reads the leaving episode's
record and what it points at (``reading``), makes the scout's one call (``scout``),
then, for each finding with no outcome, one framing call (``framing``) and, for each
memory framing keeps, retrieval and one placement call (``placement``), proposing each
memory through the write stage as a placed proposal (``writing``). Corrections are
handled when the correcting episode is processed (§3), so nothing later is read.

**Ordered, bounded, budgeted, never lossy** (ADR-0329 §16:3-§16:9). Due episodes are
taken oldest first, by ``(occurred_at, episode id)``; a run takes at most its bound of
them, and what is left waits for the next run. Before each model call, the scout's,
framing's and placement's alike (ADR-0346 §10:2), the calls recorded in the last 24 hours
are read through ``PlanStore.observer_calls_since``, and a call that would exceed the
daily budget is not made: the attempt is held and the episode waits, with nothing
dropped, and the run stops. An attempt that fails — a model call, a read, a write, a
placement stale past its count, or a reply that does not parse — is retried after a
backoff doubling from a base to a cap; an episode whose failed attempts reach the stuck
count is marked stuck, kept, and set aside, and later episodes proceed. A held attempt is
not a failed one.

**Recorded as it goes** (§16:1, §16:4). The observation record is written after the
scout, with its findings, their annotations and its declines (ADR-0346 §4:5, §4:6), and
after each finding's commit, conditionally on the revision read, with every model call
the attempt made, so the budget counts every call and a retry commits only the findings
with no outcome. A run writes nothing to the episode, links nothing to a story and adds
nothing the selector reads (§7:4).

**What a later attempt needs is on the record, never only in the process** (§12:6,
§16:1, §16:4), so a hub that stops between attempts loses nothing:

- each pending finding carries its ``supply``, the meet of every record the readings
  over it were supplied: set when the scout proposes it, and narrowed by every later
  attempt's reading before anything is written;
- what framing kept is put on the finding as ``framed`` before any placement call, and
  each memory's progress with it as the writer takes each step (``writing``);
- each write that lands is put in the finding's ``written`` with the memory marked done;
  the commit that decides the finding's outcome merges them into it and clears both in
  the same write.

So a retry, after a failure or a held budget, resumes: framing is not asked again, a
memory already done is not proposed again, and one whose proposal may have landed is
read off the store. A pending finding whose ``supply`` is not recorded — one the plan
store held before the field — is proposed again by a new scout, since its supply is
unknown and nothing may stand in for it.

**One run at a time** (§16:6): a run asked for while one is running does not start and
answers busy. The hub is one resident process per data directory, so a lock held in
the process is the whole of it; the observation record's conditional write is the
backstop.

**An episode with nothing to read is skipped by rule** (§16:7), with no model call: its
input carries no message, its rounds record no candidate, and its digests hold no
evidence item. An episode with no processing record carries no recorded trigger from
which a support's origin could be set (ADR-0328 §4:2), so it is skipped too.

**It logs stage and code-owned reasons only** (§15:7): counts, states and the names of
the steps, never a fact, a wording, a claim or an identifier that may carry personal
data.

**The person model, where the root wires its store** (ADR-0338 §9). Each run, before
its episodes, confirms the pins (§9:6, ``PinConfirmations``), and the writer confirms
them again, strictly, before each retrieval (§9:9). Each attempt reads the five fields of
the leaving episode's person, and the scout and framing are given them under the prompts'
``person`` flag (§9:1): the scout may then propose field suggestions and mark a finding
as only restating a field, which is not committed (§9:2-§9:3), and framing says of each
memory whether it states how the person wants to be spoken to and whether it matters in
every conversation, which code records as a style mark and a pin suggestion on the
memory it is held at (§9:4-§9:5). Where no store is wired, or the episode is no person's,
the flag is false and nothing is read from or written to the person model (§11:2).

**What it shows the owner goes to the diagnostic record** (ADR-0333 §2), where the record
is on: each call's request and reply, the scout's findings and declines, each finding's
outcome with what its framing and placements decided, every ``unclear`` among them
(ADR-0346 §6:5), and how each attempt ended (``entries``). A failure to write one changes
nothing here (§2:11), and nothing here reads one back (§4:1).
"""

from __future__ import annotations

import asyncio
import functools
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import structlog

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.diagnostics import failure_body
from ai_assistant.core.errors import (
    MemoryStoreError,
    ModelContentFilterError,
    ModelError,
    PersonModelStoreError,
    PlanningError,
    StoryStoreError,
)
from ai_assistant.core.reply_shapes import reply_shape_version
from ai_assistant.core.types import (
    RETIRING_OPERATIONS,
    EpisodicMemory,
    FindingOutcome,
    FindingUnwritten,
    FramedMemory,
    LabelBounds,
    MemoryOperationKind,
    ObservationAttempt,
    ObservationAttemptEnd,
    ObservationRecord,
    ObservationState,
    ObservationWrite,
    ObserverCall,
    ObserverStep,
    PersonModelWriteKind,
    Placement,
    ProposedSuggestion,
    ReplyFailure,
    SuggestionKind,
)
from ai_assistant.orchestration.observer.entries import Diagnosed, ObserverEntries
from ai_assistant.orchestration.observer.framing import (
    framed,
    framing_messages,
    framing_view,
)
from ai_assistant.orchestration.observer.person import PinConfirmations, person_of
from ai_assistant.orchestration.observer.placement import (
    placement_messages,
    placement_of,
)
from ai_assistant.orchestration.observer.prompts import (
    OBSERVER_FRAMING_PROMPT,
    OBSERVER_PLACEMENT_PROMPT,
    OBSERVER_SCOUT_PROMPT,
    PERSON_FLAG,
)
from ai_assistant.orchestration.observer.reading import EpisodeReader, episode_text
from ai_assistant.orchestration.observer.replies import (
    FramingReplyShape,
    PersonScoutReplyShape,
    PlacementReplyShape,
    ScoutReplyShape,
)
from ai_assistant.orchestration.observer.scout import (
    PersonScoutReply,
    ScoutReply,
    person_proposals,
    proposed,
    scout_messages,
)
from ai_assistant.orchestration.observer.writing import (
    FindingWriter,
    WriteLimits,
    outcome_of,
)
from ai_assistant.orchestration.remembering import REMEMBER_CAPABILITY

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pydantic import BaseModel

    from ai_assistant.core.prompts import PromptTemplate, RenderedPrompt
    from ai_assistant.core.protocols import (
        DiagnosticSink,
        MemoryStore,
        PersonModelStore,
        PlanStore,
        StoryStore,
        StructuredCompleter,
    )
    from ai_assistant.core.types import (
        CandidateDecline,
        Memory,
        MemoryPlacement,
        Message,
        ObservationFinding,
        PersonModelWrite,
    )
    from ai_assistant.orchestration.observer.framing import Framing
    from ai_assistant.orchestration.observer.person import PersonFields
    from ai_assistant.orchestration.observer.placement import PlacementView
    from ai_assistant.orchestration.observer.reading import Reading
    from ai_assistant.orchestration.observer.writing import Written
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
        since: ADR-0329 §7:5's instant: an episode that occurred before it is never due.
        relevance: The least relevance a stored memory is retrieved at by its wording
            alone (ADR-0346 §6:1).
        retrieved: The most stored memories retrieved for one framed memory (§6:1).
        recent_supports: The most recent supports a retrieved memory is shown with in
            full (§6:2).
        stale_retries: How many times a stale placement is placed again within one
            attempt (§6:7).
        labels: The bounds on a memory's situation labels (ADR-0345 §7:3).
        retry_base: The first backoff after a failed attempt (ADR-0329 §16:4).
        retry_cap: The longest backoff (§16:4).
        stuck_after: The failed attempts after which an episode is stuck (§16:5).
        per_run: The most episodes one run takes (§16:8).
        daily_calls: The most model calls in any 24 hours, every step's (§16:9).
    """

    since: datetime
    relevance: float
    retrieved: int
    recent_supports: int
    stale_retries: int
    labels: LabelBounds
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
        if min(self.retrieved, self.recent_supports, self.stale_retries) < 0:
            msg = "the observer's retrieval bounds are not negative (ADR-0346 §6)"
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
        pinned: The ``pinned`` supports its pin pass added (ADR-0338 §9:6).
    """

    busy: bool = False
    processed: int = 0
    skipped: int = 0
    waiting: int = 0
    stuck: int = 0
    held: bool = False
    pinned: int = 0


class _Held(Exception):  # noqa: N818 — a control-flow signal: the budget, not a failure
    """The daily budget would be exceeded by the next model call (§16:9)."""


class _NotRecorded(Exception):  # noqa: N818 — a control-flow signal: the record, not the attempt
    """The observation record could not be written: another writer, or the store."""


class _Unparsed(Exception):  # noqa: N818 — a control-flow signal with a code-owned name
    """A step's reply did not parse, or left a candidate unaccounted: no proposal."""

    def __init__(self, step: ObserverStep) -> None:
        super().__init__(step.value)
        self.step = step


@dataclass(slots=True)
class _Attempt:
    """One attempt's record as it is built, and the revision it was last written at.

    ``diagnosed`` is where its diagnostic entries go (ADR-0333 §2:8): set once the episode
    is read, and ``None`` before then or where the episode has no processing record.
    """

    record: ObservationRecord
    started_at: datetime
    calls: list[ObserverCall] = field(default_factory=list)
    diagnosed: Diagnosed | None = None


@dataclass(frozen=True, slots=True)
class _Decided:
    """A commit's outcome, and what its framing and placements decided, where calls did."""

    outcome: FindingOutcome
    decided: dict[str, object] | None = None


class Observer:
    """The observer: a background stage that commits what a leaving episode shows (§15:1).

    It holds by injection its two model routes, the scout's and the commit step's, which
    framing and placement both ride (ADR-0346 §10:2), the memory store, the write stage,
    the plan store, the story store and the episode selector (ADR-0329 §15:1, §15:3), the
    person-model store where one is wired (ADR-0338 §9:8), and every bound as
    :class:`ObserverLimits`. The composition root builds it; nothing here reads a setting.
    """

    def __init__(  # noqa: PLR0913 — §15:1 names every collaborator the stage holds
        self,
        *,
        scout: StructuredCompleter,
        commit: StructuredCompleter,
        memory: MemoryStore,
        writes: MemoryWriteStage,
        plans: PlanStore,
        stories: StoryStore,
        episodes: EpisodeSelector,
        limits: ObserverLimits,
        scout_prompt: PromptTemplate,
        framing_prompt: PromptTemplate,
        placement_prompt: PromptTemplate,
        now: Callable[[], datetime],
        mint: Callable[[], str] | None = None,
        diagnostics: DiagnosticSink | None = None,
        person_model: PersonModelStore | None = None,
    ) -> None:
        """Wire the observer.

        ``writes`` must write to the ``memory`` store this reads from, and ``episodes``
        must be the selector the composition root wires into understanding, so the
        window it tests is the window understanding is shown (§15:3). The type system
        cannot express either, so both are composition-root obligations.

        Args:
            scout: The scout's model route (ADR-0329 §9:9), as its structured seam
                (ADR-0354 §6:2).
            commit: The commit step's model route, which framing and placement ride
                (ADR-0346 §10:2), likewise.
            memory: The memory store episodes and memories are read from.
            writes: The write stage every write goes through (ADR-0329 §12:1).
            plans: The plan store observation and effect records are read from and
                written to (§16).
            stories: The story store a story's summaries and notes are read from
                (ADR-0347 §4).
            episodes: ADR-0276 §4's episode selector (§7:1, §15:3).
            limits: Every bound, budget and instant.
            scout_prompt: The template of ``OBSERVER_SCOUT_PROMPT``, default or
                override, as the composition root read it at start (ADR-0334 §3:5).
            framing_prompt: The template of ``OBSERVER_FRAMING_PROMPT``, likewise.
            placement_prompt: The template of ``OBSERVER_PLACEMENT_PROMPT``, likewise.
            now: The clock every record, call and write is stamped from.
            mint: Mints the fresh part of a new memory's id; a random one where
                ``None``.
            diagnostics: The diagnostic record's write seam (ADR-0333 §2:7), or ``None``
                where ``diagnostic_record`` is false and no entry is built.
            person_model: The person-model store (ADR-0338 §9:8), which must hold the
                pins of memories ``memory`` holds; ``None`` where ``person_model`` is
                off, and then nothing of the person model is read or written.

        Raises:
            ValueError: If a prompt is not a template of its step's prompt.
        """
        for template, declaration in (
            (scout_prompt, OBSERVER_SCOUT_PROMPT),
            (framing_prompt, OBSERVER_FRAMING_PROMPT),
            (placement_prompt, OBSERVER_PLACEMENT_PROMPT),
        ):
            if template.declaration != declaration:
                msg = f"the observer's step renders the {declaration.name} prompt (ADR-0334 §2)"
                raise ValueError(msg)
        self._prompts = {
            ObserverStep.SCOUT: scout_prompt,
            ObserverStep.FRAMING: framing_prompt,
            ObserverStep.PLACEMENT: placement_prompt,
        }
        self._scout = scout
        self._commit = commit
        self._memory = memory
        self._plans = plans
        self._episodes = episodes
        self._limits = limits
        self._now = checked_clock(now, owner="Observer")
        self._mint = mint or _random_id
        self._entries = ObserverEntries(diagnostics, now=self._now)
        self._reader = EpisodeReader(memory=memory, plans=plans, stories=stories)
        self._people = person_model
        self._pins = (
            None
            if person_model is None
            else PinConfirmations(people=person_model, memory=memory, writes=writes, now=self._now)
        )
        self._writer = FindingWriter(
            writes=writes,
            memory=memory,
            plans=plans,
            now=self._now,
            limits=WriteLimits(
                threshold=limits.relevance,
                bound=limits.retrieved,
                recent=limits.recent_supports,
                stale_retries=limits.stale_retries,
            ),
            pins=self._pins,
        )
        self._lock = asyncio.Lock()
        # A finding as this process last built it, while the plan store has not taken
        # the write carrying it: an outcome decided, or a write landed on a memory and
        # put in ``written``. A write of the record that fails ends the run (§16:6's
        # backstop), so the next attempt in this process starts from these rather than
        # from the record — never committing a decided finding again, and never losing
        # a landed write the record missed (§16:1).
        self._unsaved: dict[tuple[str, str], ObservationFinding] = {}

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
            pinned=outcome.pinned,
        )
        return outcome

    async def _run(self) -> RunOutcome:
        # ADR-0338 §9:6: before the episodes, with no model call and against no budget.
        pinned = 0 if self._pins is None else await self._pins.run_pass()
        window = await self._episodes(frozenset())
        queue = await self.due(window)
        outcome = RunOutcome(pinned=pinned)
        for episode, held in queue[: self._limits.per_run]:
            try:
                state = await self._attempted(episode, held)
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
        self, episode_id: str, held: ObservationRecord | None
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
            await self._entries.ended(
                Diagnosed.of(episode, started),
                ObservationAttemptEnd.FINISHED,
                ObservationState.SKIPPED,
                skipped=True,
            )
            return ObservationState.SKIPPED
        attempt = await self._open(episode_id, held, started)
        attempt.diagnosed = Diagnosed.of(episode, started)
        try:
            await self._processed(episode, attempt)
        except _Held:
            await self._close(attempt, ObservationAttemptEnd.HELD, ObservationState.WAITING)
            await self._entries.ended(
                attempt.diagnosed, ObservationAttemptEnd.HELD, ObservationState.WAITING
            )
            raise
        except (
            ModelError,
            MemoryStoreError,
            StoryStoreError,
            PlanningError,
            PersonModelStoreError,
            _Unparsed,
        ) as exc:
            return await self._failed(attempt, exc)
        await self._close(attempt, ObservationAttemptEnd.FINISHED, ObservationState.PROCESSED)
        self._forget(episode_id)
        await self._entries.ended(
            attempt.diagnosed, ObservationAttemptEnd.FINISHED, ObservationState.PROCESSED
        )
        return ObservationState.PROCESSED

    def _forget(self, episode_id: str) -> None:
        """Drop the findings this process kept beside an episode processed or read afresh."""
        for key in [key for key in self._unsaved if key[0] == episode_id]:
            del self._unsaved[key]

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
            declines=() if held is None else held.declines,
        )
        stored = await self._record(record, expected_revision=0 if held is None else held.revision)
        attempt = _Attempt(record=stored, started_at=started)
        # What this process built of a finding that the plan store never took is where
        # this attempt starts from, before anything can fail it (§16:1).
        for one in stored.findings:
            unsaved = self._unsaved.get((episode_id, one.id))
            if one.outcome is None and unsaved is not None:
                _set(attempt, _restored(unsaved, one))
        return attempt

    async def _processed(self, episode: EpisodicMemory, attempt: _Attempt) -> None:
        """Read, scout where no finding is pending yet, and commit each finding left.

        A pending finding whose supply is not recorded is proposed again over this
        attempt's reading, and those with an outcome stay as recorded (§16:4).
        """
        reading = await self._reader.read(episode)
        # ADR-0338 §2:5, §7:4: the leaving episode's person's fields, read once per attempt
        # and given to the scout and framing; none where no store is wired or it is no
        # person's.
        person = None if self._people is None else await person_of(self._people, episode)
        findings = attempt.record.findings
        unknown = any(one.outcome is None and one.supply is None for one in findings)
        if not findings or unknown:
            kept = tuple(one for one in findings if one.outcome is not None)
            self._forget(episode.id)
            await self._scouted(reading, attempt, kept, person)
        else:
            # §12:6: a record read again may have been narrowed since, so every pending
            # finding takes the meet of this attempt's reading too, never wider.
            _narrow(attempt, reading.supplied)
        for finding_id in [one.id for one in attempt.record.findings if one.outcome is None]:
            key = (episode.id, finding_id)
            current = _finding(attempt, finding_id)
            decided: _Decided | None = None
            # An outcome decided before its record failed to be written is recorded as
            # decided, never committed again over writes that already landed (§16:1).
            if current.outcome is None:
                current, decided = await self._committed(finding_id, reading, attempt, person)
            self._unsaved[key] = current
            done = tuple(
                current if one.id == finding_id else one for one in attempt.record.findings
            )
            try:
                await self._save(attempt, findings=done)
            except _NotRecorded:
                # The next attempt restores the decided finding and never decides it
                # anew, so its entry is written now or never (ADR-0333 §2:5).
                await self._outcome_entry(attempt, current, decided)
                raise
            await self._outcome_entry(attempt, current, decided)

    async def _outcome_entry(
        self, attempt: _Attempt, finding: ObservationFinding, decided: _Decided | None
    ) -> None:
        """A finding's outcome entry, where this attempt's commit decided it (§2:5)."""
        if decided is None or finding.outcome is None:
            return
        await self._entries.outcome(
            attempt.diagnosed, finding, finding.outcome, decided=decided.decided
        )

    async def _scouted(
        self,
        reading: Reading,
        attempt: _Attempt,
        kept: tuple[ObservationFinding, ...],
        person: PersonFields | None,
    ) -> None:
        """The scout's one call, and its findings and declines recorded (ADR-0346 §4).

        Each new finding carries the meet of what the scout was supplied (ADR-0329 §12:6),
        so a commit in a later attempt starts from it, and the scout's annotations
        (§4:5). A reply that leaves a candidate unaccounted is refused as one that does
        not parse is (§4:6).

        Given a person (ADR-0338 §9:1-§9:3), a finding that only restates a field is
        recorded already decided, nothing kept, and is never committed; its suggestion,
        and each the scout proposed beside its findings, is recorded before the findings
        are, so a store that fails leaves no finding behind, and the retry scouts again
        rather than losing a suggestion (ADR-0329 §16:1, §16:4).
        """
        rendered = None if person is None else person.rendered()
        shape: type[ScoutReply] = ScoutReplyShape if person is None else PersonScoutReplyShape
        reply_read = await self._call(
            attempt,
            ObserverStep.SCOUT,
            self._scout,
            lambda instruction: scout_messages(reading, instruction, person=rendered),
            shape,
            person=person is not None,
        )
        numbered_from = _next_number(kept)
        proposal = proposed(reply_read, reading, numbered_from=numbered_from)
        if proposal is None:
            raise _Unparsed(ObserverStep.SCOUT)
        supply = Placement.narrowest_of(reading.supplied)
        _log.info(
            "observer_scout",
            stage="scout",
            findings=len(proposal.findings),
            declines=len(proposal.declines),
            dropped=proposal.dropped,
        )
        findings = tuple(_updated(one, supply=supply) for one in proposal.findings)
        restating: frozenset[str] = frozenset()
        if person is not None and isinstance(reply_read, PersonScoutReply):
            proposals = person_proposals(reply_read, reading, numbered_from=numbered_from)
            restating = frozenset(proposals.restating)
            await self._suggested(person, proposals.to_record)
            not_kept = FindingOutcome(at=self._now(), unwritten=FindingUnwritten.NOT_KEPT)
            findings = tuple(
                _updated(one, outcome=not_kept) if one.id in restating else one for one in findings
            )
            _log.info(
                "observer_scout",
                stage="person",
                restating=len(restating),
                suggestions=len(proposals.to_record),
                dropped=proposals.dropped,
            )
        declines = _declines(attempt.record.declines, proposal.declines)
        await self._save(attempt, findings=(*kept, *findings), declines=declines)
        await self._entries.findings(
            attempt.diagnosed, findings, proposal.dropped, declines=proposal.declines
        )
        for one in findings:
            if one.id in restating and one.outcome is not None:
                await self._entries.outcome(attempt.diagnosed, one, one.outcome)

    async def _suggested(
        self, person: PersonFields, suggestions: Sequence[ProposedSuggestion]
    ) -> None:
        """Record each suggestion as pending, unless the store says it changes nothing.

        The store refuses a value the profile holds, an equal suggestion pending or
        dismissed, and a memory already pinned (ADR-0338 §9:2, §9:5), and validates a
        field's value as it validates a field's (§3:2): a refusal is logged under its
        code-owned reason, never the value (ADR-0329 §15:7), and the next is recorded.

        Raises:
            PersonModelStoreError: If the store cannot be written: the attempt fails, and
                the episode stays to be retried (ADR-0329 §16:4).
        """
        people = self._people
        if people is None:  # pragma: no cover - called only with a person
            return
        for one in suggestions:
            written = await people.record_suggestion(person.person_id, one)
            _refusal_logged(written, stage="suggestion")

    async def _committed(
        self, finding_id: str, reading: Reading, attempt: _Attempt, person: PersonFields | None
    ) -> tuple[ObservationFinding, _Decided]:
        """One finding's framing, placements and writes (ADR-0346 §5-§6).

        What an earlier attempt wrote — the finding's ``written`` — joins the outcome,
        and the outcome clears ``written`` and ``framed`` in the write that records it
        (ADR-0329 §16:1). Returns the finding with its outcome, and what its calls
        decided, which the outcome's diagnostic entry gives once the record holds it
        (ADR-0333 §2:5).
        """
        decided = await self._decision(finding_id, reading, attempt, person)
        outcome = decided.outcome
        _log.info(
            "observer_commit",
            stage="commit",
            ruling=None if outcome.ruling is None else outcome.ruling.value,
            unwritten=None if outcome.unwritten is None else outcome.unwritten.value,
            writes=len(outcome.writes),
            unclear=len(outcome.unclear),
            asked=len(outcome.asked),
        )
        finding = _updated(_finding(attempt, finding_id), written=(), framed=(), outcome=outcome)
        return finding, decided

    async def _decision(
        self,
        finding_id: str,
        reading: Reading,
        attempt: _Attempt,
        person: PersonFields | None,
    ) -> _Decided:
        """This commit's calls, checks and writes: what it wrote, or why nothing was.

        Framing is asked once: what it keeps is put on the finding before any placement,
        so a later attempt resumes from it (ADR-0329 §16:1, §16:4). Every step of every
        memory's write is put on the record as the writer takes it, beside what earlier
        attempts wrote. Given a person, the style and pin framing judged of each memory
        are recorded on the memory it is held at before the outcome is (ADR-0338
        §9:4-§9:5), every memory's, the earlier attempts' included.
        """
        finding = _finding(attempt, finding_id)
        earlier = finding.written
        if earlier and not finding.framed:
            # A finding the plan store held before ``framed``: its replacement's create
            # may be on the record without what it retired (§16:1).
            earlier = await self._recovered(earlier)
        framing: Framing | None = None
        records = finding.framed
        if not records:
            framing = await self._framing(finding, reading, attempt, person)
            if framing is None:
                return _Decided(
                    outcome=_unwritten(self._now(), FindingUnwritten.CHECK_FAILED, earlier)
                )
            if not framing.memories:
                reason = (
                    FindingUnwritten.CHECK_FAILED if framing.failed else FindingUnwritten.NOT_KEPT
                )
                outcome = _unwritten(self._now(), reason, earlier)
                return _Decided(outcome=outcome, decided=_decided(framing, None))
            records = tuple(
                FramedMemory(memory=one.memory, style=one.style, pin=one.pin)
                for one in framing.memories
            )

        async def progress(
            now: tuple[FramedMemory, ...], writes: tuple[ObservationWrite, ...]
        ) -> None:
            key = (attempt.record.episode, finding_id)
            updated = _updated(
                _finding(attempt, finding_id), framed=now, written=_joined(earlier, writes)
            )
            _set(attempt, updated)
            # Kept until the record carrying it is written, so a failing write of the
            # record loses no step to the next attempt in this process (§16:1).
            self._unsaved[key] = updated
            await self._save(attempt, findings=attempt.record.findings)

        if framing is not None:
            # What framing kept reaches the record before any placement call is made.
            await progress(records, ())

        set_aside: list[dict[str, object]] = []

        async def place(shown: PlacementView) -> MemoryPlacement:
            reply = await self._call(
                attempt,
                ObserverStep.PLACEMENT,
                self._commit,
                lambda instruction: placement_messages(shown, instruction),
                PlacementReplyShape,
                finding=_finding(attempt, finding_id),
            )
            return _placement_read(reply, shown, set_aside)

        annotations = finding.annotations
        written = await self._writer.write(
            records,
            texts={one: read.text for one in finding.rests_on if (read := reading.at(one))},
            supply=finding.supply or Placement(),
            narrowing=None if annotations is None else annotations.narrowing,
            place=place,
            progress=progress,
        )
        if person is not None:
            # On the memory each write left, before the outcome is recorded: a store that
            # fails fails the attempt, and the retry resumes from the record, every
            # memory done, and marks again, which the store keeps once.
            await self._marked(person, written.framed, episode=attempt.record.episode)
        outcome = outcome_of(written.framed, _joined(earlier, written.writes), at=self._now())
        return _Decided(outcome=outcome, decided=_decided(framing, written, set_aside))

    async def _recovered(
        self, written: tuple[ObservationWrite, ...]
    ) -> tuple[ObservationWrite, ...]:
        """``written``, with what each replacement on it retired, read off the store (§16:1).

        The writer before ADR-0346 put a supersession's create on the record before it
        read what that create retired, so a finding the plan store held from then may
        carry the create alone. A replacement's create names each memory it replaces
        (ADR-0328 §5:6), and each names it as successor in the retiring operation, so
        those operations are read off the store, each once, beside what is recorded.

        Raises:
            MemoryStoreError: Where they cannot be read: the attempt fails, and the
                retry reads them again.
        """
        created = [one.memory for one in written if MemoryOperationKind.CREATE in one.operations]
        if not created:
            return written
        held = await self._memory.get_history(created)
        replaced = {
            retired: memory_id
            for memory_id, memory in held.items()
            for retired in memory.operations[0].replaces
        }
        recorded = {
            one.memory for one in written if RETIRING_OPERATIONS.intersection(one.operations)
        }
        wanted = [one for one in replaced if one not in recorded]
        if not wanted:
            return written
        retired = await self._memory.get_history(wanted)
        found = [
            ObservationWrite(memory=memory_id, operations=(operation.kind,))
            for memory_id in wanted
            if (memory := retired.get(memory_id)) is not None
            for operation in memory.operations
            if operation.successor == replaced[memory_id]
        ]
        return _joined(written, found)

    async def _framing(
        self,
        finding: ObservationFinding,
        reading: Reading,
        attempt: _Attempt,
        person: PersonFields | None,
    ) -> Framing | None:
        """The finding's one framing call and code's checks of it (ADR-0346 §5).

        Returns ``None`` where a part it rests on is no longer read, which fails its
        check before any call (ADR-0329 §9:5).
        """
        view = framing_view(finding, reading)
        if view is None:
            return None
        rendered = None if person is None else person.rendered()
        reply_read = await self._call(
            attempt,
            ObserverStep.FRAMING,
            self._commit,
            lambda instruction: framing_messages(view, instruction, person=rendered),
            FramingReplyShape,
            finding=finding,
            person=person is not None,
        )
        return framed(
            reply_read,
            view,
            now=self._now(),
            mint=self._mint,
            labels=self._limits.labels,
            person=person is not None,
        )

    async def _marked(
        self, person: PersonFields, framed_memories: Sequence[FramedMemory], *, episode: str
    ) -> None:
        """The style marks and pin suggestions framing asked for (ADR-0338 §9:4-§9:5).

        Each on the memory the framed memory is held at after its write, the one
        installed or each it was folded into. The store keeps a memory already marked,
        or whose mark the person removed, unmarked again, and records no pin suggestion
        for a memory pinned or one equal to a pending or dismissed one.

        Raises:
            PersonModelStoreError: If the store cannot be written: the attempt fails, and
                the retry, resuming from the record, marks again.
        """
        people = self._people
        if people is None:  # pragma: no cover - called only with a person
            return
        for one in framed_memories:
            if not (one.style or one.pin):
                continue
            for memory_id in one.kept:
                if one.style:
                    marked = await people.add_style_mark(person.person_id, memory_id)
                    _refusal_logged(marked, stage="mark")
                if one.pin:
                    suggestion = ProposedSuggestion(
                        kind=SuggestionKind.PIN, memory_id=memory_id, episode_id=episode
                    )
                    await self._suggested(person, [suggestion])

    async def _call[T: BaseModel](  # noqa: PLR0913 — step, route, request, shape, finding, flag
        self,
        attempt: _Attempt,
        step: ObserverStep,
        route: StructuredCompleter,
        request: Callable[[RenderedPrompt], list[Message]],
        shape: type[T],
        *,
        finding: ObservationFinding | None = None,
        person: bool = False,
    ) -> T:
        """One structured call, inside the daily budget (§16:9), recorded on the attempt.

        Its given entry is written once the budget admits it and before it is made, with
        the shape's name and version (ADR-0354 §7:1), and its returned entry once it
        returns or fails (ADR-0333 §2:2), with what came back with the reply (§7:2); a
        failure raised is re-raised unchanged. The returned entry is written before a
        returned failure is acted on (§7:2): a refusal is raised as
        ``ModelContentFilterError``, where a provider's raised refusal fails the attempt,
        and any other kind is a reply that does not parse (§9:2, ADR-0329 §16:4).

        ``request`` builds the call's messages around the step's instruction, rendered
        here under ``person`` — whether the step is given a person's fields (ADR-0338
        §9:1) — so that the given entry records the ``prompt`` key, flag included, of the
        very instruction they carry (ADR-0334 §8:2, ADR-0335 §9:1). The placement prompt
        declares no flag and is rendered with none.
        """
        template = self._prompts[step]
        flags = {PERSON_FLAG: person} if PERSON_FLAG in template.declaration.flags else {}
        instruction = template.rendered(flags=flags)
        messages = request(instruction)
        at = self._now()
        made = await self._plans.observer_calls_since(at - _A_DAY)
        if made >= self._limits.daily_calls:
            raise _Held
        attempt.calls.append(ObserverCall(step=step, at=at))
        # Recorded before the call is made, so a call cancelled or lost with the process
        # mid-flight still counts against the budget (§16:9).
        await self._save(attempt, findings=attempt.record.findings)
        targets = () if attempt.diagnosed is None else (attempt.diagnosed,)
        await self._entries.given(
            targets,
            step,
            messages,
            prompt=instruction,
            finding=finding,
            reply_shape=_reply_shape(shape),
        )
        named = None if finding is None else finding.id
        try:
            reply = await route.complete_structured(messages, shape)
        except Exception as exc:
            await self._entries.returned(targets, step, failure=exc, finding=named)
            raise
        await self._entries.returned(targets, step, structured=reply, finding=named)
        if reply.failure is ReplyFailure.REFUSED:
            msg = f"the provider refused the observer's {step.value} call (ADR-0354 §9:2)"
            raise ModelContentFilterError(msg)
        if reply.value is None:
            raise _Unparsed(step)
        return reply.value

    async def _save(
        self,
        attempt: _Attempt,
        *,
        findings: tuple[ObservationFinding, ...],
        declines: tuple[CandidateDecline, ...] | None = None,
    ) -> None:
        """Write the record with the findings and the calls so far, the attempt still open."""
        record = _with_attempt(
            attempt,
            findings=findings,
            declines=declines,
            end=None,
            state=ObservationState.WAITING,
        )
        await self._carried(attempt, record)

    async def _close(
        self, attempt: _Attempt, end: ObservationAttemptEnd, state: ObservationState
    ) -> None:
        record = _with_attempt(attempt, findings=attempt.record.findings, end=end, state=state)
        await self._carried(attempt, record)

    async def _carried(self, attempt: _Attempt, record: ObservationRecord) -> None:
        """Write ``record``, built from the attempt's findings, and drop what it carries.

        Every finding this process kept unsaved for the episode was put on the attempt's
        record when the attempt began, or as it was built, so once a record built from
        those findings is written none is unsaved any more.
        """
        attempt.record = await self._record(record, expected_revision=attempt.record.revision)
        self._forget(record.episode)

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
        await self._carried(attempt, record)
        await self._entries.ended(
            attempt.diagnosed, ObservationAttemptEnd.FAILED, state, failure=_failure_of(exc)
        )
        _log.info(
            "observer_attempt",
            stage=exc.step.value if isinstance(exc, _Unparsed) else "attempt",
            result=state.value,
            reason=_reason(exc),
            failures=failures,
        )
        return state


@functools.cache
def _reply_shape(shape: type[BaseModel]) -> dict[str, str]:
    """A given entry's ``reply_shape``: the shape's name and version (ADR-0354 §7:1)."""
    return {"name": shape.__name__, "version": reply_shape_version(shape)}


def _placement_read(
    reply: PlacementReplyShape, shown: PlacementView, set_aside: list[dict[str, object]]
) -> MemoryPlacement:
    """The placement a reply states, what code set aside of it kept in ``set_aside``.

    What code did not take of the reply goes to the diagnostic record, and its count to
    the log, and never fails the attempt (#3398).

    Raises:
        _Unparsed: Where the reply places nothing shown readably (ADR-0329 §16:4).
    """
    read = placement_of(reply, shown)
    if read is None:
        raise _Unparsed(ObserverStep.PLACEMENT)
    if read.set_aside:
        _log.info("observer_placement", stage="placement", set_aside=len(read.set_aside))
        set_aside.append({"wording": shown.framed.content, "set_aside": list(read.set_aside)})
    return read.placement


def _decided(
    framing: Framing | None,
    written: Written | None,
    set_aside: Sequence[dict[str, object]] = (),
) -> dict[str, object]:
    """What a finding's framing and placements decided, for its outcome entry (§2:5).

    Each memory framing proposed, with why code refused it where it did, and each kept
    one as framed, where this attempt's framing call decided them; framing's reason
    where it kept nothing; each kept memory's placement, with its ruling and where it is
    now held; and what code set aside of this attempt's placement replies, by the wording
    placed (#3398).
    """
    kept = (
        {}
        if framing is None
        else {one.memory.content: _framed_memory(one.memory) for one in framing.memories}
    )
    return {
        "framed": None
        if framing is None
        else [{**note, "framed": kept.get(str(note["wording"]))} for note in framing.notes],
        "failed": None if framing is None else framing.failed,
        "nothing": None if framing is None else framing.nothing,
        "placed": [] if written is None else list(written.placed),
        "set_aside": list(set_aside),
    }


def _framed_memory(held: Memory) -> dict[str, object]:
    """A framed memory as its framing decided it: supports, people, labels and marks."""
    end = held.validity.valid_until
    return {
        "supports": [
            {
                "part": one.points_at.model_dump(mode="json"),
                "origin": one.origin.value,
                "direction": one.direction.value,
                "backs_as_worded": one.backs_as_worded,
                "how_sure": None if one.how_sure is None else one.how_sure.value,
                "about_when": None if one.about_when is None else one.about_when.isoformat(),
                "note": one.note,
            }
            for one in held.supports
        ],
        "subjects": list(held.subjects or ()),
        "involved": list(held.involved or ()),
        "labels": [one.text for one in held.labels],
        "marks": [one.value for one in held.marks],
        "valid_until": None if end is None else end.isoformat(),
    }


def _refusal_logged(written: PersonModelWrite, *, stage: str) -> None:
    """Log a refused person-model write by its code-owned reason, never its value."""
    if written.kind is PersonModelWriteKind.REFUSED:
        _log.info(
            "observer_person",
            stage=stage,
            result="refused",
            reason=None if written.refusal is None else written.refusal.value,
        )


def _updated(finding: ObservationFinding, **fields: object) -> ObservationFinding:
    """``finding`` with ``fields`` replaced, validated whole (§16:1)."""
    return type(finding).model_validate({**dict(finding), **fields})


def _restored(unsaved: ObservationFinding, recorded: ObservationFinding) -> ObservationFinding:
    """The finding this process kept unsaved, never wider than the record's (§12:6).

    It was built after the recorded one and carries every step it does; the supply is
    the meet of the two all the same, so a restore can only narrow a placement.
    """
    if unsaved.supply is None or recorded.supply is None:
        return unsaved
    return _updated(unsaved, supply=Placement.narrowest_of([unsaved.supply, recorded.supply]))


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

    The next write of the record carries it, before any call or write is made on it; a
    finding whose supply is unknown stays unknown.
    """
    if not supplied:
        return
    for one in attempt.record.findings:
        if one.outcome is None and one.supply is not None:
            _set(attempt, _updated(one, supply=Placement.narrowest_of([one.supply, *supplied])))


def _declines(
    held: Sequence[CandidateDecline], new: Sequence[CandidateDecline]
) -> tuple[CandidateDecline, ...]:
    """The record's declines with a scout's new ones, each candidate once (ADR-0346 §4:6)."""
    kept = {one.candidate: one for one in held}
    for one in new:
        kept.setdefault(one.candidate, one)
    return tuple(kept.values())


def _failure_of(exc: Exception) -> dict[str, object]:
    """A failed attempt's class and message, as its end entry gives them (ADR-0333 §2:6).

    The record is Tier 1, so the message is kept; an unparsed reply, which carries no
    message of its own, says which step's reply did not parse.
    """
    if isinstance(exc, _Unparsed):
        return {"class": "unparsed", "message": f"the {exc.step.value} step's reply did not parse"}
    return failure_body(exc)


def _reason(exc: Exception) -> str:
    """A failed attempt's code-owned reason: never an error's message (§15:7)."""
    if isinstance(exc, _Unparsed):
        return "unparsed"
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
    declines: tuple[CandidateDecline, ...] | None = None,
) -> ObservationRecord:
    """The record with this attempt's calls and end, the findings and the state given."""
    current = ObservationAttempt(started_at=attempt.started_at, calls=tuple(attempt.calls), end=end)
    return ObservationRecord(
        episode=attempt.record.episode,
        state=state,
        attempts=(*attempt.record.attempts[:-1], current),
        findings=findings,
        declines=attempt.record.declines if declines is None else declines,
    )


def _unwritten(
    at: datetime, reason: FindingUnwritten, earlier: Sequence[ObservationWrite] = ()
) -> FindingOutcome:
    """Nothing written by this commit, with what an earlier attempt wrote (§16:1).

    A finding the plan store held before ``framed`` may carry writes an earlier commit
    landed; they are its outcome whatever this commit decides, and are never dropped.
    """
    if earlier:
        return FindingOutcome(at=at, writes=tuple(earlier))
    return FindingOutcome(at=at, unwritten=reason)


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
