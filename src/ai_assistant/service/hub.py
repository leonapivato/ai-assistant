"""The resident process: start it, keep it, stop it (ADR-0083 §§1, 3-6, 10).

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

**Two things this process does not have yet, both by sequencing rather than
oversight.** The scheduler (ADR-0083 §§7-9) runs inside this process but is a
lane behind this one; the positions it occupies in startup and shutdown are
marked below, and are load-bearing rather than decorative — ADR-0083 §8 requires
the scheduler to be **stopped and joined before** ``Engine.aclose()``, so that
ordering is expressed here even while the thing being ordered is absent. The
transport (ADR-0084) is likewise a later lane: until it lands, readiness is
signalled by the structured log event alone, which ADR-0083 §3 names as one of
the two observables and which needs no supervisor-specific protocol.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from contextlib import contextmanager
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.app import build_engine, ensure_model_credentials
from ai_assistant.core.config import load_settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.logging import configure_logging
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART, classify
from ai_assistant.service.lock import LOCK_FILENAME, InstanceLock

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ai_assistant.core.config import Settings

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

    Args:
        settings: Loaded application settings.

    Returns:
        The process exit code.
    """
    stop = asyncio.Event()
    with _signal_handlers(stop):
        try:
            return await _start_and_run(settings, stop)
        except Exception as exc:
            code, action = classify(exc)
            _report_fault(exc, action=action, code=code)
            return code


async def _start_and_run(settings: Settings, stop: asyncio.Event) -> int:
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

    Returns:
        The process exit code.
    """
    # Step 2. Resolve the data directory, create it if absent, and take the
    # instance lock. Resolution happens *here*, once, and the resolved path is
    # handed to `build_engine` below rather than letting it resolve the setting a
    # second time: the lock, the stores and (under ADR-0084) the socket must name
    # one directory, and two resolutions of one relative or `~`-bearing setting
    # are two directories waiting to happen.
    data_dir = settings.data_dir.expanduser().resolve()
    # An OSError here — a read-only filesystem, a path that is not a directory —
    # is a deployment fault and `classify` maps it as one. It is deliberately not
    # caught: step 2 is also the writability check, and the raw errno is what
    # carries the distinction.
    data_dir.mkdir(parents=True, exist_ok=True)
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
        engine = build_engine(settings, data_dir=data_dir)
        try:
            if stop.is_set():
                return EXIT_OK
            # Step 4. The deletion sweep then the retention reclaim, at the
            # position ADR-0074 §8 ratified. A resident process improves on the
            # CLI here without changing anything: because the hub restarts after a
            # crash, the reclaim that finishes an interrupted deletion now runs
            # after *every* crash rather than at the next command a user types.
            await engine.start()

            # Step 5 is where the scheduler starts (ADR-0083 §7, §8). It is a lane
            # behind this one; until it lands the enabled job set is empty, which
            # is what the readiness event below reports.

            # Step 6. Begin accepting requests, and only then signal readiness.
            # The transport is ADR-0084's lane, so there is no door yet and this
            # step is the log event alone — one of the two observables §3 names,
            # and the one that needs no supervisor-specific protocol. §14's
            # constraint on the later lane is that the transport must not accept
            # before the *other* readiness conditions hold; it goes above this
            # line, not below it.
            if stop.is_set():
                return EXIT_OK
            _log.info(
                "hub_ready",
                pid=os.getpid(),
                data_dir=str(data_dir),
                jobs=[],
            )
            await stop.wait()
        finally:
            # ADR-0083 §8: service shutdown stops and joins the scheduler
            # **before** calling `Engine.aclose()`, so that after the join no job
            # is in flight and the engine's drain has nothing of the scheduler's
            # left to wait for. The scheduler's own loop is the one thing
            # `Engine._tracked` does not cover — every *job* is a public engine
            # call and is therefore in `_inflight` already. That join belongs on
            # this line, above the close.
            #
            # Phase A and phase B of the drain are the engine's (§4): it owns the
            # tracked set, so bounding and cancelling it can only be done there.
            await engine.aclose()
    finally:
        lock.release()
    return EXIT_OK


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


def _report_fault(exc: BaseException, *, action: str, code: int) -> None:
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

    These messages are operational text carrying no Tier 0/1 content (ADR-0004
    §5): they name settings keys, paths and identifiers, never memory content and
    never a conversation.
    """
    _log.error(
        "hub_startup_failed",
        exit_code=code,
        cause=str(exc),
        error_class=type(exc).__name__,
        operator_action=action or None,
    )
    print(f"hub: cannot start: {exc}", file=sys.stderr)
    if code == EXIT_DEPLOYMENT:
        print(f"hub: {action}", file=sys.stderr)
        print(
            "hub: this will not be fixed by restarting; the deployment must change.",
            file=sys.stderr,
        )
