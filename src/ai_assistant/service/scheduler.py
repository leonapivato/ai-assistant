"""The hub's internal scheduler: one loop, per-job due instants (ADR-0083 §§7-9).

**One loop, a table of jobs, serial execution, fixed delay after completion.** The
loop runs every due job in a fixed order, one at a time, then sleeps until the
earliest next due instant. A job's next run is scheduled from its *completion*,
not from its start, which is what makes a job structurally unable to overlap
itself — ADR-0076 §2 requires a sweep to "**drain to an empty batch**", so a tick
is a walk to exhaustion whose duration is a function of the backlog rather than of
the interval, and a fixed-*rate* schedule would let a long walk be re-entered by
the next tick.

**It lives here, above the composition root, and every job is a public ``Engine``
call.** ADR-0083 §8: cadence is a property of a deployment, not of the request
pipeline, and ``orchestration`` owns the pipeline. Holding an ``Engine`` and
nothing else — no concrete store, no subsystem import — is also what makes
ADR-0076 §5's "a scheduler is a second caller of the same read" literally true:
this is a client of the same façade the CLI is a client of.

**That is also what closes the shutdown race**, and the reasoning is worth having
here rather than only in the ADR. ``Engine._tracked`` wraps every public method, so
a job whose body is ``engine.<operation>()`` has its underlying store work in
``_inflight`` already and the engine's drain waits for it exactly as it waits for a
``converse``. What is *untracked* is only this loop, and that is closed by ordering
rather than by ownership: service shutdown stops and joins the scheduler **before**
calling ``Engine.aclose()`` (see :mod:`ai_assistant.service.hub`). Belt and braces
for the race window, :class:`Scheduler` treats the ``RuntimeError`` that
``_reject_if_closing`` raises as **stop**, not as a job failure to log and retry.

**Starvation is accepted rather than engineered away** (§7). A long job delays its
siblings, and that is tolerable because a missed or late tick is never a
correctness bug: ADR-0007 §2 enforces retention at *read* time, and every job on
the list is a physical reclaim or a re-derivation of something a read path already
computes. Serialising buys a scheduler that is one thing to reason about, one thing
to cancel and one thing to drain. §7 attaches a revisit trigger to that choice —
*when a job's typical runtime approaches its interval*, which consolidation
(leg 7) is likely to do first — and this module deliberately does not pre-empt it.

**Elapsed time is ``asyncio.sleep``** (§9), which is loop-monotonic, needs no
contract and is cancellable — which is how phase A of shutdown stops it promptly.
ADR-0026's Revisit clause does not fire, because nothing here measures a duration
across a durable boundary: **no job has a durable "when did I last run"**, so there
is no catch-up to compute and nothing to persist. Two costs are named in §9 rather
than discovered later — a suspended host does not advance the sleep, and wall-clock
corrections still reach the *jobs'* own comparisons (#277 is unchanged by a
resident process).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

import structlog

from ai_assistant.orchestration.engine import ENGINE_SHUTTING_DOWN

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence

    from ai_assistant.core.config import Settings
    from ai_assistant.orchestration.engine import Engine

_log = structlog.get_logger(__name__)


class JobBody(Protocol):
    """One scheduled unit of work: a no-argument call on the engine façade.

    Every job is a **public** ``Engine`` method, bound (ADR-0083 §8). The return
    type is ``object`` because the scheduler never looks at it — see
    :meth:`Scheduler._run_job` for why it must not.
    """

    def __call__(self) -> Awaitable[object]:
        """Do the job's work once, to exhaustion."""
        ...


@dataclass(frozen=True, slots=True)
class Job:
    """A named piece of maintenance and how often it runs.

    ``interval`` is the delay *after completion*, not a period: :class:`Scheduler`
    re-arms the job at ``completion + interval``.
    """

    #: Stable identifier for the log and for ``hub_ready``'s job list.
    name: str
    #: The fixed delay after completion. Finite and strictly positive.
    interval: timedelta
    #: The bound engine method this job calls.
    run: JobBody

    def __post_init__(self) -> None:
        """Refuse an interval that is not exactly a positive ``timedelta``.

        ADR-0083 §7's rule is that "every duration this ADR adds is a ``timedelta``
        refused at load time unless it is **finite** and strictly positive".
        ``Settings`` refuses one at load (``gt=timedelta(0)``); this is the same rule
        restated where the invariant is actually *used* — a scheduler constructed in
        a test, or from a future job table that reads no setting, must not be able to
        arm a job that becomes due the instant it finishes. That is not a
        configuration nit: on a completion-scheduled loop a zero interval turns a
        retention purge into a hot loop against SQLite, and it is the one failure
        this loop cannot absorb.

        **The type check is what makes "finite" true, and it is not pedantry.**
        ``timedelta`` is subclassable, and a subclass whose ``total_seconds()``
        returns ``nan`` passes every comparison a positivity check can make —
        ``nan <= 0`` is ``False`` — and then poisons the due instant it is added to,
        so ``due > now`` and ``delay > 0`` are both ``False`` and the loop spins
        without ever sleeping. A *native* ``timedelta`` cannot hold a non-finite
        value (its constructor overflows first), so requiring the exact type **is**
        the finiteness guarantee, and it needs no second check that could never fire
        on a value which passed the first. ``core.config``'s ``_only_a_duration``
        makes the identical argument with ``type(value) is timedelta``, for the
        identical reason: nothing that merely converts to a duration is silently
        accepted as one.

        The comparison is then against ``timedelta(0)`` directly rather than through
        ``total_seconds()``, so the guard never routes a duration through a float at
        all.

        Raises:
            TypeError: If ``interval`` is not exactly a ``timedelta``.
            ValueError: If it is not strictly positive.
        """
        if type(self.interval) is not timedelta:
            msg = (
                f"job {self.name!r} must have an interval that is exactly a timedelta, got "
                f"{self.interval!r} of type {type(self.interval).__name__}; a subclass may "
                f"report a non-finite total_seconds(), which no positivity check can catch "
                f"and which makes the loop spin (ADR-0083 §7)"
            )
            raise TypeError(msg)
        if self.interval <= timedelta(0):
            msg = (
                f"job {self.name!r} must have a strictly positive interval, got "
                f"{self.interval!r}; 'disabled' is expressed by leaving the job out of "
                f"the table, never by a zero interval (ADR-0083 §7)"
            )
            raise ValueError(msg)


def jobs_for(engine: Engine, settings: Settings) -> tuple[Job, ...]:
    """Build ADR-0083 §7's job table for one engine, in the ADR's own order.

    **Only enabled jobs are returned.** §7 makes "disabled" ``None`` and never
    ``0``, following ``confirmation_ttl``'s and ``deferral_ttl``'s existing
    convention, so that "off" and "as fast as possible" cannot be confused by a
    value — which is the one confusion a scheduler cannot afford, because the two
    look identical in a config file. A disabled job is therefore absent from the
    table rather than present and skipped, and ``hub_ready`` reports the names that
    are actually armed.

    Five jobs, and each is a decision an ADR argues rather than describes:

    * **Retention purge** — ``MemoryStore.purge_expired`` *and*
      ``DeferralStore.purge``, as **one** job, because ADR-0078 §10 item 8 says the
      deferral queue's purge "is wired wherever ``purge_expired`` is wired and
      inherits the same fate" and that "inventing a second sweeping mechanism for
      one store would be the thing that has to be undone at leg 5" (#493).
    * **Conversation sweep** — the same pair ``Engine.start()`` already runs, at the
      third of the three positions ADR-0074 §8 ratified. It is idempotent and "can
      run any number of times", and ADR-0076 §5 is explicit that the scheduler
      "inherits this method unchanged" — so this job is that method, not a copy of
      it.
    * **Observation** — disabled by default, and that is deliberate (§7): without a
      durable cursor (ADR-0083 §13) a periodic run re-reads the same recent window
      and spends a model call each time, and it cannot reach the turns the window
      has already passed. Enabling it on a timer before the cursor exists buys
      repeated cost and no new coverage.
    * **Calendar reader** — leg 6's read-only ingestion (ADR-0093 §6), and the one
      job whose disabled default is *only* about consent. §7 is emphatic that
      "nothing may read a user's personal files because a default said so — not
      that anything technical is missing", so ``calendar_reader_interval`` is
      ``None`` until an operator sets it (§7a) and the job is simply absent until
      then.

      **It is not observation's kind of disabled, and §6 says so in as many
      words**: "A reader's job may ship enabled once §9's gate is discharged. The
      reason observation ships disabled is specific to observation and does not
      transfer." §9's gate is ADR-0092, which is ratified — so an operator who
      arms this job gets a job that works, where arming observation would buy
      "repeated cost and no new coverage" whatever the operator wanted. The
      difference is §5's: a reader's bound moves with the clock, so every run
      recomputes its window from scratch and nothing accumulates behind a cursor
      that does not exist. Stating this is the point of the ADR — left unstated,
      the next lane reads the observation default as the house posture for
      scheduled ingestion and ships a switch nobody can safely flip.

      ``Settings`` refuses an interval whose source path is unset (ADR-0093 §7a),
      so this entry can never arm a job with nothing to read: the incoherent
      fourth state of §7a's matrix fails at load, where a scheduler that omitted
      the requested job would instead report health while running nothing.

    * **Consolidation** — leg 7's chunked walk (ADR-0106, ADR-0111), and the third
      kind of disabled default in one table. It is not the calendar reader's, whose
      default is only about consent, and it is not observation's, whose default is
      about a cursor that did not exist: this job **has** its cursor (ADR-0114) and
      needs no grant, so nothing technical is missing and nobody's files are read.
      What it spends is a model call per chunk, unattended, and every tainted
      proposal it makes becomes a question a user has to answer (ADR-0106 §6). A
      deployment that has not decided it wants that should not acquire it by
      upgrading, so ``consolidation_interval`` is ``None`` until an operator sets
      it. ADR-0111 §11 declines the default for a job it does not land; the lane
      that landed the job took it.

      **Arming it owes ADR-0111 §4's in-chunk deadline check, which is open**
      (#820): a chunk's writes reach the ``Embedder`` through
      ``MemoryStore.write_atomic``, and that runs unbounded in a worker thread, so
      a hung backend holds this serial loop past any run budget. §4 makes such a
      deadline "a precondition of being chunked at all". The exposure is shared
      with the two jobs that already write, and this is simply the first *chunked*
      job, where §4's clause bites.

      **It is the job ADR-0083 §7's revisit condition named** — "revisit when a
      job's typical runtime approaches its interval, which is what consolidation
      (leg 7) is likely to do first" — and the answer is ADR-0111 §4's bounded run
      rather than concurrency. Its run budget and chunk size are ``Settings``, so
      the delay it imposes on a sibling is a figure an operator can read off the
      configuration rather than an unknown.

    **Confirmation deadlines are deliberately not here.** The roadmap names them as
    this scheduler's, and §7 is the one place that sentence does not survive contact
    with what is ratified below it: there is no operation to reclaim an expired
    confirmation (ADR-0059 §3, #333) and the deadline it would enforce is not yet
    written (#525), so a job over a column of nulls would sweep nothing and look
    healthy doing it. Nothing goes unenforced meanwhile — the lifetime is enforced
    at *answer* time by ``_check_fresh``, so an expired confirmation is unanswerable
    whether or not anything sweeps.

    Args:
        engine: The façade every job calls. Each job holds a **bound method** of
            this object and nothing else.
        settings: Where each interval comes from, so cadence is configuration
            rather than a contract change (ADR-0077 §8, via ADR-0083 §7).

    Returns:
        The enabled jobs, in §7's fixed order.
    """
    table: tuple[tuple[str, timedelta | None, JobBody], ...] = (
        ("retention_purge", settings.retention_purge_interval, engine.purge_expired),
        ("conversation_sweep", settings.conversation_sweep_interval, engine.start),
        ("observation", settings.observation_interval, engine.observe),
        ("calendar_reader", settings.calendar_reader_interval, engine.ingest),
        ("consolidation", settings.consolidation_interval, engine.consolidate),
    )
    return tuple(
        Job(name=name, interval=interval, run=run)
        for name, interval, run in table
        if interval is not None
    )


class Scheduler:
    """Runs a table of jobs on one loop until it is stopped (ADR-0083 §§7-9).

    Constructed with its jobs already built (:func:`jobs_for`), started once, and
    stopped exactly once by :meth:`aclose`. It owns no resources: the engine's
    lifetime brackets its own, and every job's underlying work is tracked by the
    engine rather than by this object.
    """

    def __init__(self, jobs: Sequence[Job]) -> None:
        """Hold the job table; nothing runs until :meth:`start`.

        Args:
            jobs: The jobs to run, in the order they should be attempted when more
                than one is due at the same instant. An empty table is legal and
                produces a scheduler that starts, does nothing and stops — which is
                what a deployment that disabled every job asked for.

        Raises:
            ValueError: If two jobs share a name. A name is this table's **key**,
                not a label: due instants are held per name, so a duplicate would
                let the first job re-arm the shared entry before the loop reached
                the second — and the second would then be skipped at every tick,
                forever, while ``hub_ready`` listed it and nothing logged its
                absence. §7 says the loop "runs every due job", and a job that
                never runs while reporting healthy is the exact failure mode
                ADR-0078 §1's exposure cap is lost to. Names are also what every
                log line and the readiness event report, so two jobs sharing one
                would make those unreadable even if the loop coped.
        """
        self._jobs = tuple(jobs)
        names = [job.name for job in self._jobs]
        if len(set(names)) != len(names):
            repeated = sorted({name for name in names if names.count(name) > 1})
            msg = (
                f"job names must be unique; {repeated} appears more than once. A name is "
                f"the key a due instant is held under, so a duplicate is a job that is "
                f"silently never run (ADR-0083 §7)"
            )
            raise ValueError(msg)
        self._task: asyncio.Task[None] | None = None

    @property
    def job_names(self) -> tuple[str, ...]:
        """The names of the armed jobs, for ``hub_ready``'s ``jobs`` field."""
        return tuple(job.name for job in self._jobs)

    @property
    def running(self) -> bool:
        """Whether the loop has been started and not yet joined."""
        return self._task is not None

    def start(self) -> None:
        """Arm every job and begin the loop on the running event loop.

        Not ``async``: there is nothing to await, and making it a coroutine would
        invite a caller to believe the first tick had happened by the time it
        returned. It has not — the loop task is merely scheduled.

        Raises:
            RuntimeError: If the scheduler is already running. Two loops over one
                engine would run every job twice, which is precisely the
                self-overlap §7's completion-scheduling exists to make impossible.
        """
        if self._task is not None:
            msg = "the scheduler is already running"
            raise RuntimeError(msg)
        self._task = asyncio.create_task(self._run(), name="hub-scheduler")

    async def aclose(self) -> None:
        """Stop the loop and **join** it; idempotent, and safe if never started.

        ADR-0083 §8 puts this call *before* ``Engine.aclose()``, and the order is
        the whole mechanism: after this returns, no job is in flight, so the
        engine's drain has nothing of the scheduler's left to wait for.

        **Stopping is cancellation, not a polite flag**, because the join has to be
        prompt: it happens before phase A's budget starts, so an unbounded wait for
        a long-running job here would spend the supervisor's stop timeout outside
        the phase that was designed to bound it. Cancelling is safe precisely
        because a job is a public engine call: ``Engine._tracked`` runs the
        underlying work as a **shielded** task the engine holds, so cancelling this
        loop abandons only the *await*, and the work itself stays in ``_inflight``
        for the drain that follows to wait on (ADR-0042 §2, ADR-0054).

        A loop that ended with an exception is logged rather than raised: shutdown
        must not be derailed by the thing it is shutting down, and the jobs
        themselves cannot get here (:meth:`_run_job` absorbs them), so this can only
        be a fault in the loop and is worth seeing.
        """
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        # `asyncio.wait` rather than `await task`: the task's own `CancelledError`
        # is a *result* here rather than something raised into a shutdown path, and
        # a cancellation arriving from *outside* still propagates out of the wait
        # instead of being swallowed by a `suppress`.
        await asyncio.wait({task})
        if not task.cancelled() and (failure := task.exception()) is not None:
            _log.error(
                "hub_scheduler_loop_failed",
                error_class=type(failure).__name__,
                cause=str(failure),
            )

    async def _run(self) -> None:
        """The loop: run what is due, in order, one at a time, then sleep.

        **Every job is due at start.** The alternative — first due one interval out
        — was declined: a hub restarted more often than its longest interval would
        then never sweep at all, and the retention purge is exactly the job whose
        absence ADR-0078 §1's exposure cap is measured by (#493). The cost is that
        the conversation sweep runs once more at boot than it strictly must, since
        ``Engine.start()`` has already run it at startup step 4 — and that cost is
        nil by construction: ADR-0074 §8 makes the pair idempotent and says it "can
        run any number of times". Paying one redundant sweep per boot to keep the
        job table uniform is a better trade than a per-job "skip the first tick"
        rule that would need its own reasoning for each job added later.

        Due instants live on the event loop's own monotonic clock, not on the
        injected ``Clock``. §9 draws exactly that line: waiting is loop-monotonic
        work that needs no contract, while *comparing stored instants* — an
        ``expires_at`` against now — is wall-clock work the jobs do behind the
        façade, where ``Clock`` already is.
        """
        loop = asyncio.get_running_loop()
        due = {job.name: loop.time() for job in self._jobs}
        while due:
            for job in self._jobs:
                if due[job.name] > loop.time():
                    continue
                if not await self._run_job(job):
                    return
                # Re-armed from *completion*, so a job cannot overlap itself no
                # matter how long its walk to exhaustion took (§7).
                due[job.name] = loop.time() + job.interval.total_seconds()
            delay = min(due.values()) - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)

    async def _run_job(self, job: Job) -> bool:
        """Run one job once, absorbing its failure.

        **A failing job never takes the process down** (§7): the failure is logged
        with its class (ADR-0004 §5) and the job is retried at its next due instant.
        Nothing in the job list is load-bearing for correctness, so escalating a
        sweep failure to a process exit would trade a harmless backlog for an
        outage.

        **The one failure that is not a failure** is the ``RuntimeError``
        ``Engine._reject_if_closing`` raises. ADR-0083 §8 requires that be treated
        as *stop*, not as a job failure to log and retry — belt and braces for the
        window between ``Engine.aclose()`` setting ``_closing`` and this loop being
        joined. It is recognised by :data:`~ai_assistant.orchestration.engine.ENGINE_SHUTTING_DOWN`,
        the engine's own message constant, so the two sides cannot drift; treating
        *every* ``RuntimeError`` as a shutdown would turn a real bug into a silent
        clean exit.

        ``CancelledError`` is a ``BaseException`` and is deliberately not caught: it
        is :meth:`aclose` stopping the loop, and it must reach the loop task.

        **The job's result is never logged.** The scheduler is generic over jobs and
        cannot know which results are safe to render — an ``ObservationReport``
        names beliefs, which is Tier 1 content, and ADR-0004 §5 keeps that out of
        the operational log. What is logged is the job's name and how long it took,
        which is what an operator watching a resident process needs.

        Args:
            job: The job to run.

        Returns:
            ``True`` to keep looping, ``False`` if the engine is shutting down.
        """
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            await job.run()
        except RuntimeError as exc:
            if str(exc) == ENGINE_SHUTTING_DOWN:
                _log.info("hub_scheduler_stopping", job=job.name, detail=str(exc))
                return False
            self._log_failure(job, exc, elapsed=loop.time() - started)
        except Exception as exc:
            self._log_failure(job, exc, elapsed=loop.time() - started)
        else:
            _log.info(
                "hub_scheduler_job_completed",
                job=job.name,
                elapsed_seconds=round(loop.time() - started, 3),
            )
        return True

    def _log_failure(self, job: Job, exc: Exception, *, elapsed: float) -> None:
        """Record a job's failure with its class, and keep going (ADR-0004 §5)."""
        _log.warning(
            "hub_scheduler_job_failed",
            job=job.name,
            error_class=type(exc).__name__,
            cause=str(exc),
            elapsed_seconds=round(elapsed, 3),
            detail="the job is retried at its next due instant; the hub keeps running",
        )
