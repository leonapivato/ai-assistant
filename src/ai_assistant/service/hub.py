"""The resident process: start it, keep it, stop it (ADR-0083 §§1, 3-6, 8, 10).

**The hub is a single, long-lived, foreground process.** It does not fork, does
not daemonise, and writes its log to standard output. Exactly one instance runs
per data directory. It needs no client to start it and no client can start it,
and when it is not running there is a reason a human can read — which is what the
exit codes in :mod:`ai_assistant.service.exits` exist for.

Everything above is a decision, not an implementation preference: the deployment
this is designed for is a dedicated always-on machine, and the supervisor is the
one thing deliberately not hard-coded. ADR-0083 §3 states a contract (S1-S7) that
a supervisor satisfies (D1-D4); systemd is named there as *a* realisation of it
and nothing here depends on systemd.

**The scheduler runs inside this process** (:mod:`ai_assistant.service.scheduler`),
and where it sits in the sequence is load-bearing rather than decorative: ADR-0083
§8 requires it to be **stopped and joined before** ``Engine.aclose()``, because
that ordering is what leaves the engine's drain with nothing of the scheduler's
left to wait for.

**The door is the transport** (:mod:`ai_assistant.service.transport`, ADR-0084),
and where it opens and closes in the sequence is a decision rather than a
convenience: it begins accepting at ADR-0083 §3's **step 6**, after the sweeps and
before the readiness event, so "no request is ever served against a half-built
engine"; and it stops accepting and unlinks the socket at the **start of phase A**,
so a new client meets one clear "not running" rather than a connection that hangs
for the length of an unbounded phase B.

**Both ends of the lifecycle are legible, and the symmetry is the point** (#559).
A hub that will not start says why, to stderr and the log (§5, §6). A hub that is
stopping now says how it stopped: ``hub_scheduler_stopped`` when the join
completes, and ``hub_shutdown_completed`` carrying the exit code, which of §4's two
phases the drain ended in, and how long each part took. Without that last event the
four states an operator most needs to tell apart — phase A still within budget,
phase B awaiting after a cancellation, phase B blocked on something that will never
finish, and already finished — all look identical: silence after
``hub_shutdown_requested``.

**A failure is reported against the half of the lifecycle it happened in** (#581).
The exit code is not: §5's codes answer "come back or stay down" and that question
has one answer wherever the fault arose, so :func:`~ai_assistant.service.exits.classify`
stays the only classifier and keeps its single call site. What differs is the text an
operator reads. "cannot start" for a closer that would not release its connection
sends them to look at configuration and permissions, on a hub that had been serving
for weeks; and because §4's shutdown is two-phase, "could not shut down" is not
specific enough either — draining and then failing to release the instance lock is a
different fact from never draining at all. So a shutdown fault names the part that
failed and what the drain had already done.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant import __version__
from ai_assistant.app import build_composition, ensure_model_credentials
from ai_assistant.core.config import load_settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.logging import configure_logging
from ai_assistant.orchestration.engine import DrainPhase
from ai_assistant.service import datadir
from ai_assistant.service.admin import AdminListener
from ai_assistant.service.configuration import ConfigurationStamp
from ai_assistant.service.enrolment import ENROLMENTS_FILENAME, DeviceRegistry, EnrolmentStore
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART, classify
from ai_assistant.service.lock import LOCK_FILENAME, InstanceLock
from ai_assistant.service.overlay import OverlayIdentityUnavailableError, local_agent
from ai_assistant.service.remote import RemoteListener
from ai_assistant.service.scheduler import Scheduler, jobs_for
from ai_assistant.service.transport import ConnectionBudget, Listener

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ai_assistant.core.config import Settings
    from ai_assistant.orchestration.engine import Engine

_log = structlog.get_logger(__name__)

#: How long a losing instance keeps trying before giving up (ADR-0083 §1).
#:
#: **Nothing rests on this length**, and §1 says so explicitly: the window is a
#: noise filter, not a correctness mechanism. It exists to absorb a supervisor
#: that overlaps a restart with an outgoing hub's drain. It cannot be sized to
#: cover that drain — phase B is unbounded — which is precisely why giving up is a
#: *restartable* exit rather than a fatal one. A setting would imply the number
#: mattered.
_LOCK_RETRY_WINDOW: Final = timedelta(seconds=5)

#: How long to wait between attempts inside :data:`_LOCK_RETRY_WINDOW`.
_LOCK_RETRY_INTERVAL: Final = timedelta(milliseconds=250)

#: ``SIGTERM`` and ``SIGINT`` both mean *drain and stop*, **identically**, so
#: ``Ctrl-C`` in a foreground run behaves exactly as the supervisor's stop does
#: (ADR-0083 §4).
_STOP_SIGNALS: Final = (signal.SIGTERM, signal.SIGINT)

#: ``SIGHUP`` is ignored **explicitly**. There is no configuration reload in this
#: version — a restart is the reload (ADR-0083 §13) — and ADR-0083 §4's reasoning
#: is that "a signal that silently does nothing is worse than one that is
#: documented as doing nothing". Installing a handler that logs is what makes the
#: difference observable rather than asserted.
_IGNORED_SIGNALS: Final = (signal.SIGHUP,)


class _ShutdownStage(StrEnum):
    """The part of ADR-0083 §4's shutdown a failure came out of (#581).

    **"During shutdown" is not one moment**, because §4's shutdown is two-phase and
    §8 puts three other things around it. A message saying only "could not shut
    down" would be as wrong in its own way as "cannot start" is: it reads as *the
    drain failed* to anyone who knows what phase B costs, and a hub that drained
    cleanly and then could not release its instance lock has lost nothing at all.
    So the stage is named, and the value doubles as the log field.

    The order below is the order they run in.
    """

    #: :meth:`~ai_assistant.service.transport.Listener.stop_accepting` — the door
    #: closes at the start of phase A (ADR-0084 §1), before anything else. Both
    #: doors, where a remote listener is configured (ADR-0124 §2): they are one
    #: stage because they are one act — the hub stops accepting.
    CLOSING_THE_DOOR = "closing_the_door"
    #: :meth:`~ai_assistant.service.scheduler.Scheduler.aclose` — stopped and
    #: joined before the engine is closed (ADR-0083 §8).
    STOPPING_THE_SCHEDULER = "stopping_the_scheduler"
    #: :meth:`Engine.aclose` — §4's phases A and B together.
    DRAINING = "draining"
    #: :meth:`~ai_assistant.service.transport.Listener.aclose` — the connections
    #: whose peers never spoke again, let go once the drain is done.
    RELEASING_CONNECTIONS = "releasing_connections"
    #: The instance lock, released last of all (ADR-0083 §1).
    RELEASING_THE_LOCK = "releasing_the_lock"


#: How each stage reads in an operator message, after "shutdown failed while".
#: Separate from :class:`_ShutdownStage`'s values because those are log fields, and
#: a structured field that has to double as English ends up being neither.
_STAGE_PHRASES: Final[dict[_ShutdownStage, str]] = {
    _ShutdownStage.CLOSING_THE_DOOR: "closing the door",
    _ShutdownStage.STOPPING_THE_SCHEDULER: "stopping the scheduler",
    _ShutdownStage.DRAINING: "draining in-flight work",
    _ShutdownStage.RELEASING_CONNECTIONS: "letting go of the remaining connections",
    _ShutdownStage.RELEASING_THE_LOCK: "releasing the instance lock",
}

#: What the drain had done by the time the shutdown failed, in operator-facing
#: words. Keyed by the phase because that *is* the answer to the question a stop
#: that went wrong raises first: did my in-flight work finish?
_DRAIN_ACCOUNT: Final[dict[DrainPhase, str]] = {
    DrainPhase.NOT_RUN: "in-flight work was not drained, and may not have finished",
    DrainPhase.QUIESCED: "in-flight work had already finished on its own",
    DrainPhase.CANCELLED: (
        "in-flight work was cancelled at the drain budget, then awaited to completion"
    ),
}


@dataclass(slots=True)
class _ShutdownRecord:
    """What the shutdown sequence did, so its completion can be reported (#559).

    A record rather than a return value because the two halves of the answer are
    produced in different places: how the drain went is known inside
    :func:`_start_and_run`'s ``finally``, and the **exit code** is known only in
    :func:`serve`, which is the one place a failure is classified (ADR-0083 §5).
    Threading a mutable record down is what lets one event carry both without
    duplicating the classification or the timing.

    ``reached`` distinguishes "the shutdown sequence ran" from "startup failed
    before there was anything to shut down". A hub that never built an engine has
    no drain to report and says so by staying silent — the startup fault is the
    event that matters there, and inventing a completion event for it would be the
    "crash loop wearing a diagnosis" §5 warns about, in miniature.
    """

    #: Whether the shutdown sequence was entered at all.
    reached: bool = False
    #: The jobs that were armed when the stop arrived.
    jobs: tuple[str, ...] = ()
    #: How long stopping and joining the scheduler took (ADR-0083 §8).
    scheduler_join_seconds: float | None = None
    #: How long ``Engine.aclose()`` took — phases A and B together (§4).
    drain_seconds: float | None = None
    #: Which of §4's two phases the drain ended in.
    phase: DrainPhase = DrainPhase.NOT_RUN
    #: The whole shutdown, join and drain together.
    elapsed_seconds: float | None = None
    #: The stage a failure escaped from, or ``None`` if none did (#581).
    failed_at: _ShutdownStage | None = None
    #: The failure a cleanup was already unwinding from, if any. The exception
    #: itself rather than its text, because ADR-0083 §5's verdict is read off the
    #: class and the ``errno``, not off the message (:func:`_classify_pair`).
    unwinding_from: BaseException | None = None

    @property
    def shutdown_failure(self) -> _ShutdownStage | None:
        """The stage the shutdown failed at, or ``None`` if the fault was not its.

        **``reached`` alone is not this test, and using it would invert the very bug
        #581 reports.** The shutdown sequence runs in a ``finally``, so it also runs
        when *startup* fails at step 4, 5 or 6 — a store that will not open, a
        socket path too long to bind. In every one of those the record is `reached`
        and the exception that escapes is still a startup fault, correctly reported
        as one. What distinguishes the two is not that shutdown ran but that
        shutdown *raised*, which is what :attr:`failed_at` records.

        Three conditions, one for each way a fault can arrive holding a stage:

        * :attr:`reached` — the instance lock is released outside the shutdown
          sequence as well, so a start that failed before an engine existed still
          unwinds through a stage. A fault there is that failed start, not a
          shutdown that never happened.
        * :attr:`failed_at` — the shutdown must have *raised*, not merely run.
        * :attr:`unwinding_from` — **and it must not have been unwinding from
          something else.** A ``finally`` that raises replaces the exception it was
          unwinding from, so a start that failed and *then* failed to clean up hands
          ``serve`` a cleanup fault with no trace of the start in it. Framing that as
          a shutdown would tell an operator their hub stopped badly when it never
          came up at all — #581's own defect, mirrored.

        A stop signal that arrives mid-startup is deliberately *not* excluded by
        that last condition, and readiness would be the wrong test for it: nothing
        was in flight, the hub was asked to stop, and a shutdown that then failed is
        a shutdown that failed.

        Returned rather than answered ``True``/``False`` so the caller carries the
        stage it needs into the message without re-reading a field it has already
        proved is set.
        """
        if not self.reached or self.unwinding_from is not None:
            return None
        return self.failed_at

    @property
    def replaced_cause(self) -> BaseException | None:
        """The failure a raising cleanup displaced, when it displaced one.

        Conditioned on :attr:`failed_at` because that is what says the exception
        ``serve`` caught came from a cleanup at all. Where nothing in the shutdown
        raised, the exception ``serve`` holds *is* the one recorded here, and
        printing it a second time under "already failed with" would be noise
        dressed as an extra fact.
        """
        return self.unwinding_from if self.failed_at is not None else None


@dataclass(slots=True)
class _Remote:
    """Everything the remote listener needs, built only where it is configured.

    ADR-0124 §2: "The remote listener is off unless it is configured on. A hub with
    no remote-listener configuration binds only ADR-0084 §1's loopback socket, and
    the loopback socket is bound whether or not the remote listener is." So this is
    ``None`` on an unconfigured hub and nothing about the loopback path changes.

    The enrolment record, the control socket and the listener are one bundle
    because they have one lifetime: the record exists to be admitted against, and
    the control socket exists to write it. A hub with no remote listener has no use
    for either, and would need an overlay agent it is not running to build them.

    Attributes:
        store: The durable enrolment record.
        registry: Its live view, and where a revocation takes effect (ADR-0124 §8).
        listener: The remote door.
        admin: The hub-local entry point for the owner's acts (§6).
    """

    store: EnrolmentStore
    registry: DeviceRegistry
    listener: RemoteListener
    admin: AdminListener


def main() -> int:
    """Start the hub, run it, and return the process's exit code.

    The console script's entry point. It is a *second* console script rather than
    an ``assistant hub`` subcommand, and ADR-0084 §6 explains why the natural
    instinct is wrong: a subcommand would live in ``interfaces``, which would then
    have to import ``service``, and ADR-0083 §8 forbids anything importing
    ``service`` at all.

    The first startup step happens here rather than in :func:`serve` because it
    has to: **loading settings is step 1**, and until it succeeds there is no log
    level to configure logging with. A settings failure is a deployment fault, so
    it is reported and the process stays down (ADR-0083 §3 step 1, §5).

    Returns:
        The process exit code — one of :data:`~ai_assistant.service.exits.EXIT_OK`,
        :data:`~ai_assistant.service.exits.EXIT_RESTART` or
        :data:`~ai_assistant.service.exits.EXIT_DEPLOYMENT`.
    """
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        code, action = classify(exc)
        _report_fault(exc, action=action, code=code)
        return code
    configure_logging(settings)
    return asyncio.run(serve(settings))


async def serve(settings: Settings) -> int:
    """Run the hub to completion on the current event loop.

    Separated from :func:`main` so a test can drive the whole lifecycle — signals
    included — without a subprocess, and so the settings a deployment loads and
    the process that serves them are not welded together.

    **Every failure that escapes startup is classified here and nowhere else**
    (:func:`~ai_assistant.service.exits.classify`), which is what keeps ADR-0083
    §5's "the boundary is a test, not a list" from decaying into a list scattered
    across the sequence.

    **It is also where the shutdown's completion is reported** (#559), for the same
    reason: the exit code is decided here, and an event that could not name the code
    would leave an operator with the one question they asked. So the timings and the
    phase come up from :func:`_start_and_run` in a record and are logged once the
    code is known — including on the path where shutdown itself failed, which is
    exactly the case where knowing whether work had been cancelled matters most.

    **The wording, and only the wording, forks on which half of the lifecycle the
    failure came from** (#581). One ``except`` and one :func:`classify` call are
    what keep §5's "the boundary is a test, not a list" from decaying into a list;
    the fork is below that, on the same record the completion event already reads.

    Args:
        settings: Loaded application settings.

    Returns:
        The process exit code.
    """
    stop = asyncio.Event()
    shutdown = _ShutdownRecord()
    with _signal_handlers(stop):
        try:
            code = await _start_and_run(settings, stop, shutdown)
        except Exception as exc:
            replaced = shutdown.replaced_cause
            code, action = _classify_pair(exc, replaced)
            stage = shutdown.shutdown_failure
            if stage is None:
                _report_fault(exc, action=action, code=code, replaced=replaced)
            else:
                _report_shutdown_fault(exc, shutdown, stage=stage, action=action, code=code)
    _report_shutdown(shutdown, code=code)
    return code


def _classify_pair(escaped: BaseException, displaced: BaseException | None) -> tuple[int, str]:
    """ADR-0083 §5's verdict when a cleanup fault erased the failure under it.

    **§5's test is about the situation, not about an exception object**: "would
    restarting, unchanged, ever succeed?" A filesystem access fault earns ``78``
    "wherever in startup it surfaces" (§3 step 3, §5), and it does not stop having
    surfaced because a ``finally`` raised over it. Classifying only what escaped
    hands a supervisor ``1`` and buys "an infinite restart loop against an
    unchanging ``EACCES``" — §5's own words for the failure it exists to prevent.

    **It only ever raises a verdict to** :data:`EXIT_DEPLOYMENT`, **never lowers
    one**, and that asymmetry is the whole safety argument. §5 puts the burden the
    other way — "where a new fault does not obviously answer the question, the
    answer is ``1``: a spurious restart is recoverable and a spurious ``78`` is an
    outage" — so nothing here may invent a stay-down verdict. Every ``78`` it
    returns is one :func:`~ai_assistant.service.exits.classify` itself returned, for
    a fault that really happened, and the action printed alongside is that fault's.

    Reads as a no-op on every ordinary path: ``displaced`` is non-``None`` only when
    a cleanup raised over a fault that had already ended the start.

    Args:
        escaped: The exception that reached :func:`serve`.
        displaced: The one it replaced while unwinding, if it replaced any.

    Returns:
        The exit code, and the operator action to print with it.
    """
    code, action = classify(escaped)
    if displaced is None or code == EXIT_DEPLOYMENT:
        return code, action
    displaced_code, displaced_action = classify(displaced)
    if displaced_code == EXIT_DEPLOYMENT:
        return displaced_code, displaced_action
    return code, action


def _note_unwinding_from(record: _ShutdownRecord, exc: BaseException) -> None:
    """Keep the fault a cleanup is about to erase, if it has not erased one yet.

    A ``finally`` that raises substitutes its own exception for the one it was
    unwinding from, and ``__context__`` is not read here — :func:`classify` follows
    ``__cause__`` alone, deliberately. So without this the reason the hub is down is
    reachable only from a traceback nobody prints (#581).

    **Both guards carry an argument, and neither is defensive.**

    * ``failed_at is None`` — once a stage has raised, the exception in hand *is*
      the cleanup's rather than something the cleanup displaced. Recording it would
      have a genuine shutdown failure describe itself as the thing it interrupted.
    * ``unwinding_from is None`` — the two call sites nest, so the outer one sees
      whatever the inner already recorded. First writer wins, because the earlier
      fault is the one further from the cleanups and nearer the cause.

    Args:
        record: The shutdown record to note it on.
        exc: The exception now unwinding.
    """
    if record.failed_at is None and record.unwinding_from is None:
        record.unwinding_from = exc


@contextmanager
def _during(record: _ShutdownRecord, stage: _ShutdownStage) -> Iterator[None]:
    """Attribute anything escaping this block to ``stage``, and to nothing else.

    Recording on the way *out* rather than on the way in is what makes the
    attribution right in a ``finally``: when the drain raises and the connection
    release that follows it succeeds, the drain is still what failed. A scheme that
    marked each stage as it was entered would hand the blame to whichever cleanup
    ran last.

    ``BaseException`` because the record is a statement about what happened, not
    about what :func:`serve` will report — a shutdown that lost to a cancellation
    should not leave a record claiming it completed. :func:`serve` reads
    :attr:`_ShutdownRecord.failed_shutting_down` only on the path where it caught an
    ``Exception``, so widening here narrows nothing there.
    """
    try:
        yield
    except BaseException:
        record.failed_at = stage
        raise


def _report_shutdown(shutdown: _ShutdownRecord, *, code: int) -> None:
    """Record that the drain finished, how long it took, and how it ended (#559).

    The counterpart to ``hub_shutdown_requested``, and the event whose absence made
    four states indistinguishable: phase A still within budget, phase B awaiting
    after a cancellation, phase B blocked on something that will never finish, and
    already finished. All four look identical when the last line in the log is the
    request.

    ``drain_phase`` is the one an operator reads first. ADR-0083 §4 leaves phase B's
    await **unbounded** on purpose — bounding it would mean abandoning a store call
    whose worker thread still holds a connection the next statement closes — so
    "which phase" is also "was this bounded". The budget it was measured against
    rides along, because a drain time means little without it.

    The transition *into* phase B already has its own event: ``Engine._drain`` logs
    ``shutdown_drain_budget_exceeded`` at the moment it cancels, which is the point
    a deployment's stop timeout is being spent. This event is the other half — what
    that spending bought.

    Operational text only (ADR-0004 §5): job names, durations, an exit code.

    Args:
        shutdown: What the shutdown sequence did.
        code: The process exit code, known only once startup faults are classified.
    """
    if not shutdown.reached:
        return
    _log.info(
        "hub_shutdown_completed",
        exit_code=code,
        drain_phase=shutdown.phase.value,
        drain_seconds=shutdown.drain_seconds,
        scheduler_join_seconds=shutdown.scheduler_join_seconds,
        elapsed_seconds=shutdown.elapsed_seconds,
        jobs=list(shutdown.jobs),
    )


async def _start_and_run(settings: Settings, stop: asyncio.Event, shutdown: _ShutdownRecord) -> int:
    """ADR-0083 §3's startup sequence, then serve until stopped, then §4's shutdown.

    In order, and **no step begins before the previous one has succeeded** — which
    is the whole content of §3 and the reason this reads as one straight line
    rather than a set of independently-initialised parts.

    A stop that arrives *during* startup is honoured between steps rather than
    ignored until the end. The process unwinds through the same ``finally``
    blocks a normal stop uses, so a hub killed halfway through a slow embedder
    load still closes what it opened and still releases the lock.

    Args:
        settings: Loaded application settings.
        stop: Set by a stop signal; awaited once the hub is serving.
        shutdown: Filled in as the shutdown sequence runs, for :func:`serve` to
            report once the exit code is known (#559).

    Returns:
        The process exit code.
    """
    # Step 2. Prepare the data directory, then take the instance lock — in that
    # order, because taking the lock means opening a file inside the directory.
    #
    # The path needs no resolving here: `Settings` refuses a relative value and
    # canonicalises the rest (ADR-0084 §1), so this and the composition root read
    # one directory by construction rather than by each doing the same arithmetic
    # and hoping to agree.
    #
    # `prepare` creates it `0700` if absent and validates the whole ancestor
    # chain; an `OSError` it raises — a read-only filesystem, a path that is not a
    # directory — is deliberately not caught, because the raw errno is what tells
    # a stay-down access fault from a transient one (§3 step 3, §5).
    data_dir = settings.data_dir
    datadir.prepare(data_dir)
    lock = InstanceLock(data_dir / LOCK_FILENAME)
    if not await _acquire_instance_lock(lock, data_dir):
        return EXIT_RESTART
    try:
        if stop.is_set():
            return EXIT_OK
        # Step 3. Everything that can fail without touching a store fails first.
        # The credential check is here rather than inside `build_engine` because
        # it is the *hub's* question and not the CLI's (issue #530): a one-shot
        # command that needs no model must not start requiring a key.
        ensure_model_credentials(settings)
        # The build returns the engine **and** the two things ADR-0119 §9's
        # startup stamp cannot get anywhere else: the trace store's append seam,
        # and the effective ``search`` limit of each cardinality control, which is
        # a property of how the root constructed two collaborators and not of any
        # ``Settings`` field.
        composed = build_composition(settings, data_dir=data_dir)
        engine = composed.engine
        # Built before the ``try`` so the ``finally`` can always join it, including
        # on a stop that arrives between here and step 5. An unstarted scheduler's
        # ``aclose`` is a no-op, which is what makes that unconditional join safe.
        scheduler = Scheduler(jobs_for(engine, settings))
        # One budget, held by every listener the hub binds (ADR-0124 §7): "adding
        # it may not let the hub's total concurrent connections exceed
        # `hub_max_connections`", and two listeners each honouring the figure
        # independently would mean the hub honours neither.
        budget = ConnectionBudget(
            max_connections=settings.hub_max_connections,
            max_pending_handshakes=settings.hub_max_pending_handshakes,
        )
        listener = Listener(engine, settings, data_dir=data_dir, budget=budget)
        remote: _Remote | None = None
        try:
            # ADR-0119 §9's configuration stamp, "after the stores are open and
            # before the API accepts a request". Both bounds are satisfied
            # anywhere between step 3 and step 6; here, at the earliest legal
            # point, is where it buys the most: the ``CONFIGURATION`` trace is
            # then the **first** trace of every hub run, so "a gap between a
            # shutdown and the next configuration trace is a hub that was not
            # running" is exact rather than approximate, and a start that fails at
            # step 4 still leaves its configuration dated.
            #
            # **Not a seventh startup step, which is why it is above the stop
            # check and not below it.** ADR-0083 §3's sequence is fixed and each
            # of its steps is a precondition of the next; this is neither. It
            # cannot fail (§5 subordinates it — ``record`` never raises), nothing
            # later depends on it, and a hub whose stamp was lost is a hub that
            # started normally with a Tier 2 log record saying so. Gating it on the
            # between-steps stop check would make it a step in the one way that
            # matters — §9's requirement is unconditional once the stores are
            # open, and "a carrier that fires on every startup … cannot be
            # forgotten" is not true of one a stop signal can race. A hub stopped
            # here leaves a configuration trace with no operation after it, which
            # reads correctly as a hub that came up and served nothing.
            await ConfigurationStamp(
                sink=composed.trace_sink,
                retrieval_search_limit=composed.retrieval_search_limit,
                conflict_search_limit=composed.conflict_search_limit,
            ).record(settings)

            if stop.is_set():
                return EXIT_OK
            # Step 4. The deletion sweep then the retention reclaim, at the
            # position ADR-0074 §8 ratified. A resident process improves on the
            # CLI here without changing anything: because the hub restarts after a
            # crash, the reclaim that finishes an interrupted deletion now runs
            # after *every* crash rather than at the next command a user types.
            await engine.start()

            # Step 5. Start the scheduler (ADR-0083 §7, §8). After step 4 so its
            # first conversation-sweep tick cannot race the startup sweep it
            # duplicates, and before readiness so the job list the event reports is
            # a list of jobs that are actually armed.
            scheduler.start()

            # Step 6. Begin accepting requests, and only then signal readiness —
            # in that order, which is ADR-0083 §14.2 ("the transport must not
            # accept before readiness") read against §3: every *other* readiness
            # condition already holds by the time the listener binds, and the
            # event is what says so to a supervisor. The stale-socket unlink
            # inside `start` is safe here and nowhere earlier, because the
            # instance lock has been held since step 2 (ADR-0084 §1).
            if stop.is_set():
                return EXIT_OK
            # The remote apparatus is built *before* either door opens, so a hub
            # whose overlay agent cannot confirm its bind address never accepts a
            # connection at all — ADR-0124 §2's "refused at load time rather than
            # bound", at the latest point this deployment can still refuse.
            remote = await _build_remote(engine, settings, data_dir=data_dir, budget=budget)
            await listener.start(build=__version__)
            if remote is not None:
                await remote.listener.start(build=__version__)
                await remote.admin.start()
            _log.info(
                "hub_ready",
                pid=os.getpid(),
                data_dir=str(data_dir),
                socket=str(listener.path),
                remote=None
                if remote is None
                else f"{remote.listener.address}:{remote.listener.port}",
                jobs=list(scheduler.job_names),
            )
            await stop.wait()
        except BaseException as exc:
            # Before the `finally` below runs the shutdown sequence — which is the
            # whole point. Once a stage of that sequence has raised, this exception
            # is gone from everything anyone reads.
            _note_unwinding_from(shutdown, exc)
            raise
        finally:
            await _shut_down(
                engine,
                scheduler,
                listener,
                remote,
                shutdown,
                budget=settings.shutdown_drain_seconds,
            )
    except BaseException as exc:
        # The second capture point, for the steps *above* the inner ``try``:
        # credentials, the composition root, the two constructors. Nothing of the
        # shutdown has run for those, but the lock release below can still erase
        # them. The guards inside are what make this one safe here (#581).
        _note_unwinding_from(shutdown, exc)
        raise
    finally:
        # Outside `_shut_down` because the lock outlives it: it is taken at step 2
        # and released here whether or not there was ever an engine to drain. Named
        # as a stage anyway, so a hub that drained cleanly and then could not let go
        # of the lock says that rather than "could not shut down" (#581).
        with _during(shutdown, _ShutdownStage.RELEASING_THE_LOCK):
            lock.release()
    return EXIT_OK


async def _build_remote(
    engine: Engine,
    settings: Settings,
    *,
    data_dir: Path,
    budget: ConnectionBudget,
) -> _Remote | None:
    """Build the remote listener's apparatus, or nothing where it is not configured.

    The overlay agent is asked one question here — what this machine is on the
    overlay — and its answer supplies two things ADR-0124 needs before a device can
    be admitted: the hub's own overlay identity, which §6 discloses beside every
    credential because §4 makes it "the thing a destination has to match", and the
    addresses §2's bind restriction is checked against
    (:meth:`~ai_assistant.service.remote.RemoteListener.start`).

    Args:
        engine: The in-process engine this hub owns.
        settings: The deployment's configuration.
        data_dir: The directory the hub owns.
        budget: The hub's shared ceilings (ADR-0124 §7).

    Returns:
        The apparatus, or ``None`` on a hub with no remote-listener configuration.

    Raises:
        ConfigurationError: If the overlay agent cannot say what this machine is.
            A stay-down deployment fault: an operator who configured a remote
            listener and has no agent running has a deployment to fix, and a hub
            that came up serving loopback alone would be silently ignoring the
            configuration they set (ADR-0083 §5, ruling 4).
    """
    if settings.hub_remote_address is None:
        return None
    agent = local_agent()
    try:
        identity = (await agent.hub_identity()).identity
    except OverlayIdentityUnavailableError as exc:
        msg = (
            f"a remote listener is configured on {settings.hub_remote_address}, and the "
            f"overlay agent on this machine could not be asked what this machine is "
            f"({exc}). Enrolment discloses the hub's own overlay identity and admission "
            f"reads a device's, so neither can happen without it; start the overlay agent, "
            f"or unset ASSISTANT_HUB_REMOTE_ADDRESS to serve the loopback socket alone"
        )
        raise ConfigurationError(msg) from exc
    store = EnrolmentStore(data_dir / ENROLMENTS_FILENAME)
    registry = DeviceRegistry(store, hub_identity=identity)
    return _Remote(
        store=store,
        registry=registry,
        listener=RemoteListener(engine, settings, registry=registry, agent=agent, budget=budget),
        admin=AdminListener(registry, data_dir=data_dir),
    )


async def _shut_down(  # noqa: PLR0913 — one parameter per thing ADR-0083 §4's sequence closes, in the order it closes them
    engine: Engine,
    scheduler: Scheduler,
    listener: Listener,
    remote: _Remote | None,
    record: _ShutdownRecord,
    *,
    budget: timedelta,
) -> None:
    """ADR-0083 §4's shutdown, in §8's order, recording what it did (#559).

    **The order is the mechanism, not a preference.** §8:

        Service shutdown stops and joins the scheduler *before* calling
        ``Engine.aclose()``.

    After that join no job is in flight, so the engine's drain has nothing of the
    scheduler's left to wait for. The scheduler's own loop is the one thing
    ``Engine._tracked`` does not cover — every *job* is a public engine call and is
    therefore in ``_inflight`` already, drained exactly as a ``converse`` is.

    Phase A and phase B are the engine's (§4): it owns the tracked set, so bounding
    and cancelling can only be done there. What this function adds is the account of
    it, because an unbounded phase B with no observability is a hub whose only
    remaining signal is that it has not exited yet.

    **Every part is timed, and the timing survives a failure.** If ``aclose`` raises
    — a closer that could not release its connection — the drain is still recorded
    before the exception leaves, so the completion event :func:`serve` logs
    afterwards is about the shutdown that actually happened rather than about the
    one that was planned.

    **The door closes first**, before the scheduler and before the drain. ADR-0084
    §1 puts the listener's stop and the socket's unlink "at the start of phase A",
    and taking it first is what makes the rest honest: no new request can arrive
    while the scheduler is being joined or while tracked work is finishing, so the
    drain converges on a set that is only shrinking. Connections already accepted
    are in-flight work and ADR-0083 §4's phases own them; what
    :meth:`~ai_assistant.service.transport.Listener.aclose` collects afterwards is
    only a connection whose peer never spoke again.

    Args:
        engine: The façade to drain and close.
        scheduler: The loop to stop and join first. Never started is fine.
        listener: The door to close before either.
        remote: The remote listener, its control socket and its record, on a hub
            that was configured for one (ADR-0124 §2), or ``None``.
        record: Filled in as each part completes.
        budget: Phase A's configured budget, reported so a drain time can be read
            against the figure it was measured against.
    """
    record.reached = True
    record.jobs = scheduler.job_names
    began = time.monotonic()
    try:
        with _during(record, _ShutdownStage.CLOSING_THE_DOOR):
            await listener.stop_accepting()
            if remote is not None:
                await remote.listener.stop_accepting()
                await remote.admin.stop_accepting()
        with _during(record, _ShutdownStage.STOPPING_THE_SCHEDULER):
            await scheduler.aclose()
        record.scheduler_join_seconds = round(time.monotonic() - began, 3)
        _log.info(
            "hub_scheduler_stopped",
            jobs=list(record.jobs),
            elapsed_seconds=record.scheduler_join_seconds,
            drain_budget_seconds=budget.total_seconds(),
        )
        drain_began = time.monotonic()
        try:
            with _during(record, _ShutdownStage.DRAINING):
                await engine.aclose()
        finally:
            record.drain_seconds = round(time.monotonic() - drain_began, 3)
            record.phase = engine.drain_phase
            with _during(record, _ShutdownStage.RELEASING_CONNECTIONS):
                await listener.aclose()
                if remote is not None:
                    await remote.listener.aclose()
                    await remote.admin.aclose()
                    remote.store.close()
    finally:
        record.elapsed_seconds = round(time.monotonic() - began, 3)


async def _acquire_instance_lock(lock: InstanceLock, data_dir: Path) -> bool:
    """Take the instance lock, retrying for a bounded few seconds (ADR-0083 §1).

    The retry absorbs a supervisor that overlaps a restart with an outgoing hub's
    drain. It cannot be sized to *cover* that drain, because §4's phase B is
    unbounded — which is exactly why failing here is restartable rather than
    fatal.

    Args:
        lock: The lock to take.
        data_dir: The directory it guards, for the diagnostic.

    Returns:
        ``True`` if the lock is held, ``False`` if another instance holds it.
    """
    deadline = time.monotonic() + _LOCK_RETRY_WINDOW.total_seconds()
    while True:
        if lock.acquire():
            return True
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(_LOCK_RETRY_INTERVAL.total_seconds())

    # The pid is a *hint* and is reported only when one can be read. `flock`
    # exposes no portable query for its holder, so the holder records its own pid
    # after acquiring — which leaves a contender able to read the file empty or
    # stale. A message that unconditionally promised a pid would eventually print
    # a wrong one, and a wrong pid in an operator message is worse than none.
    pid = lock.recorded_pid()
    _log.warning(
        "hub_instance_lock_contended",
        data_dir=str(data_dir),
        lock=str(lock.path),
        holder_pid_hint=pid,
        detail=(
            "the data directory is held by another instance; it is either serving "
            "or draining, and a later start succeeds either way"
        ),
    )
    return False


@contextmanager
def _signal_handlers(stop: asyncio.Event) -> Iterator[None]:
    """Install the process's signal dispositions for the duration of the block.

    Installed **before** startup begins, not after readiness, so a stop that
    arrives during a slow engine build is honoured rather than landing on the
    default disposition — which for ``SIGTERM`` is death, and death here is
    ``SIGKILL``'s cost without ``SIGKILL``'s excuse.

    Removed on the way out so the process leaves no handler behind referring to an
    event nobody is waiting on, which matters when :func:`serve` is driven
    repeatedly inside one test process.
    """
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    try:
        for sig in _STOP_SIGNALS:
            loop.add_signal_handler(sig, _request_stop, stop, sig)
            installed.append(sig)
        for sig in _IGNORED_SIGNALS:
            loop.add_signal_handler(sig, _log_ignored_signal, sig)
            installed.append(sig)
        yield
    finally:
        for sig in installed:
            loop.remove_signal_handler(sig)


def _request_stop(stop: asyncio.Event, sig: signal.Signals) -> None:
    """Ask for a drain and stop; a second request changes nothing (ADR-0083 §4).

    **Escalation is refused deliberately.** ``aclose`` is already memoised and
    cancellation-safe, and an in-process "abrupt" mode would be a second, weaker
    way to do what ``SIGKILL`` already does uninterceptably — while costing the
    ADR-0029 §4 bookkeeping that graceful shutdown exists to keep. So an operator
    hitting ``Ctrl-C`` twice gets a line saying the shutdown is already running,
    not a faster exit.
    """
    if stop.is_set():
        _log.info("hub_shutdown_already_in_progress", signal=sig.name)
        return
    _log.info("hub_shutdown_requested", signal=sig.name)
    stop.set()


def _log_ignored_signal(sig: signal.Signals) -> None:
    """Record that a signal was received and deliberately does nothing."""
    _log.info(
        "hub_signal_ignored",
        signal=sig.name,
        detail="there is no configuration reload in this version; a restart is the reload",
    )


def _report_shutdown_fault(
    exc: BaseException,
    record: _ShutdownRecord,
    *,
    stage: _ShutdownStage,
    action: str,
    code: int,
) -> None:
    """Print a *shutdown* failure's cause, where it happened, and what drained (#581).

    The counterpart to :func:`_report_fault` and deliberately not a parameter on it:
    the two share a shape and nothing else. A start that failed has produced nothing
    an operator has to account for, so its remedy is the whole message. A stop that
    failed has already run some of ADR-0083 §4, and the first question it raises is
    not "what do I change" but **"did my in-flight work finish"** — which is why the
    drain's account is printed before any remedy, and printed unconditionally.

    **The exit code and the operator action are the same ones a start would get**,
    from the same :func:`~ai_assistant.service.exits.classify` call. §5's question —
    would restarting, unchanged, ever succeed? — has one answer wherever the fault
    arose, and an ``EACCES`` a closer hit is as unfixable by restarting as one the
    opener hit. So only the framing moves: the closing line says the *next start*
    will meet the same condition, because this process is already on its way out and
    telling it not to restart would be telling it what it is doing.

    Operational text carrying no Tier 0/1 content (ADR-0004 §5), like every other
    message on this path.

    Args:
        exc: The exception that escaped the shutdown sequence.
        record: What the shutdown had done by the time it did.
        stage: The part that failed, as
            :attr:`~_ShutdownRecord.shutdown_failure` reported it.
        action: The operator action from ``classify``, empty when none is asked.
        code: The process exit code.
    """
    _log.error(
        "hub_shutdown_failed",
        exit_code=code,
        failed_at=stage.value,
        drain_phase=record.phase.value,
        cause=str(exc),
        error_class=type(exc).__name__,
        operator_action=action or None,
    )
    print(f"hub: shutdown failed while {_STAGE_PHRASES[stage]}: {exc}", file=sys.stderr)
    print(f"hub: {_DRAIN_ACCOUNT[record.phase]}.", file=sys.stderr)
    if code == EXIT_DEPLOYMENT:
        print(f"hub: {action}", file=sys.stderr)
        print(
            "hub: the next start will meet the same condition; the deployment must change.",
            file=sys.stderr,
        )


def _report_fault(
    exc: BaseException, *, action: str, code: int, replaced: BaseException | None = None
) -> None:
    """Print a startup failure's cause, and its remedy when there is one.

    ADR-0083 §5 requires **every** deployment fault to print its cause and the
    operator action before exiting, to stderr *and* to the log, and that
    requirement is how the owner's ruling is discharged: a hub that is down is
    down for a reason a human can read. stderr as well as the log because the log
    may be going somewhere an operator is not looking at yet, and this is the
    moment they most need to be told.

    A restartable fault prints no action, because none is being asked of anyone —
    inventing an instruction there would be the "crash loop wearing a diagnosis"
    §5 warns about, in the other direction.

    **Startup, and only startup.** A failure out of the shutdown sequence goes to
    :func:`_report_shutdown_fault` instead — the classification is shared, the
    wording is not (#581). Note that "startup" here includes a start that unwound
    *through* a shutdown which itself succeeded: the fault is still the one that
    stopped the hub coming up, and that is what this says.

    **``replaced`` is the start that a failing cleanup erased.** A ``finally`` that
    raises substitutes its own exception for the one it was unwinding from, so on
    that path ``exc`` is the cleanup's and the reason the hub is down is nowhere in
    it. It is printed second rather than first because ``exc`` is the one that
    reached :func:`serve`; :func:`_classify_pair` is what keeps the code and the
    action beside it consistent with *both*, so the two lines cannot disagree about
    whether a human has to act.

    These messages are operational text carrying no Tier 0/1 content (ADR-0004
    §5): they name settings keys, paths and identifiers, never memory content and
    never a conversation.

    Args:
        exc: The exception that ended the start.
        action: The operator action from ``classify``, empty when none is asked.
        code: The process exit code.
        replaced: The earlier failure ``exc`` displaced while unwinding, if any.
    """
    _log.error(
        "hub_startup_failed",
        exit_code=code,
        cause=str(exc),
        error_class=type(exc).__name__,
        operator_action=action or None,
        replaced_cause=str(replaced) if replaced is not None else None,
        replaced_error_class=type(replaced).__name__ if replaced is not None else None,
    )
    print(f"hub: cannot start: {exc}", file=sys.stderr)
    if replaced is not None:
        print(f"hub: the start had already failed with: {replaced}", file=sys.stderr)
    if code == EXIT_DEPLOYMENT:
        print(f"hub: {action}", file=sys.stderr)
        print(
            "hub: this will not be fixed by restarting; the deployment must change.",
            file=sys.stderr,
        )
