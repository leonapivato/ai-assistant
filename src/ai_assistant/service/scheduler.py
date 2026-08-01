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
from typing import TYPE_CHECKING, Protocol

import structlog

from ai_assistant.orchestration.engine import ENGINE_SHUTTING_DOWN

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence
    from datetime import timedelta

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
        """Refuse a non-positive interval, independently of ``Settings``.

        ``Settings`` already refuses one at load (``gt=timedelta(0)``, ADR-0083
        §7), and this is the same guard restated where the invariant is actually
        *used* — a scheduler constructed in a test, or from a future job table that
        does not read a setting, must not be able to arm a job that becomes due the
        instant it finishes. That is not a configuration nit: on a
        completion-scheduled loop a zero interval turns a retention purge into a hot
        loop against SQLite, and it is the one failure this loop cannot absorb.

        Raises:
            ValueError: If ``interval`` is not strictly positive.
        """
        if self.interval.total_seconds() <= 0:
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

    Three jobs, and each of the three is a decision §7 argues rather than describes:

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
        """
        self._jobs = tuple(jobs)
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
