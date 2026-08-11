"""The resident process: how it starts, what it refuses, how it stops (ADR-0083).

The engine is faked here, deliberately and by the project's own rule that a
subsystem is tested against its contract and stood in for elsewhere. Nothing below
is about what an engine does; it is about **order**, **classification** and
**cleanup** — the three things a resident process gets wrong invisibly and a CLI
never had to get right at all.

Order, because ADR-0083 §3 makes startup a fixed sequence in which no step begins
before the previous one has succeeded, and every one of those orderings is
load-bearing: the lock before any store, so exclusivity is not a race; readiness
last, so nothing observes a half-built engine; and the scheduler stopped and joined
before ``Engine.aclose()`` (§8), asserted with a job **actually in flight**, because
an idle scheduler leaves no window to get wrong and a test over one would pass for
an implementation that closed the engine first.

Classification, because the owner's ruling behind §5 and §6 is that if the hub is
not running there must be a legible reason — and a crash loop is a process that
never explains itself, while a fatal refusal a supervisor keeps restarting is a
crash loop wearing a diagnosis.

Cleanup, because a hub that fails to start must leave nothing holding the data
directory. The lock is what the next start needs, so every failure path is tested
for having released it.
"""

from __future__ import annotations

import asyncio
import errno
import os
import signal
from typing import TYPE_CHECKING, Any, cast

import pytest
import structlog

from ai_assistant.app import Composition
from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ConfigurationError, IncompatibleStateError, TraceStoreError
from ai_assistant.core.types import EvaluationTrace, TraceKind
from ai_assistant.orchestration.engine import DrainPhase, PurgeReport
from ai_assistant.service import hub
from ai_assistant.service.configuration import SEAM_STARTUP
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART
from ai_assistant.service.lock import LOCK_FILENAME, InstanceLock
from ai_assistant.testing import FakeTraceSink

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import TraceSink
    from ai_assistant.orchestration.engine import Engine

_marker = structlog.get_logger("tests.service.fake")

#: How long a fake step parks so a signal it raised can be handled. Generous
#: relative to the work involved (delivery is immediate; this only has to survive
#: one poll pass) and paid by exactly one test.
_SIGNAL_SETTLE_SECONDS = 0.05


class FakeEngine:
    """Stands in for the ``Engine`` the composition root would return.

    It emits its own structlog events so that engine milestones and the hub's own
    events land in **one** ordered record — which is what lets "readiness is the
    last thing in startup" be asserted as an ordering rather than inferred from
    two separate spies.
    """

    def __init__(self) -> None:
        self.started = 0
        self.closed = 0
        self.purged = 0
        self.observed = 0
        self.ingested = 0
        self.consolidated = 0
        self.reconsidered = 0
        #: Run inside ``start()``. Tests use it to signal the process at a point
        #: where the hub's own handlers are certainly installed.
        self.on_start: Callable[[], None] | None = None
        #: Whether ``start()`` parks after the hook. Off by default, so a signal
        #: raised there is handled at the hub's *next* suspension — which is
        #: ``stop.wait()``, i.e. after readiness. On, the signal lands while
        #: startup is still running, which is the other case worth testing.
        self.settle = False
        #: What :attr:`drain_phase` reports once ``aclose`` has run. The real engine
        #: records it inside its own drain (ADR-0083 §4) and the hub only reads it,
        #: so a fake that never moved it would let the completion event's phase
        #: field pass without ever carrying anything but its default.
        self.drain_phase = DrainPhase.NOT_RUN

    async def start(self) -> None:
        self.started += 1
        _marker.info("fake_engine_started")
        if self.on_start is not None:
            self.on_start()
        if self.settle:
            await _settle()

    async def purge_expired(self) -> PurgeReport:
        self.purged += 1
        _marker.info("fake_engine_purged")
        # ``traces=None`` is "the horizon is keep-forever, so no trace sweep ran"
        # (ADR-0119 §10) — the honest report for a stand-in that holds no store.
        return PurgeReport(records=0, questions=0, traces=None)

    async def observe(self, *, conversation_id: str | None = None) -> None:
        self.observed += 1
        _marker.info("fake_engine_observed")

    async def ingest(self) -> None:
        # Leg 6's read-only ingestion (ADR-0093 §6). Present whether or not a
        # deployment arms the job, because `jobs_for` builds §7's whole table
        # before filtering it by interval — a stand-in missing a method the real
        # façade carries fails the hub's *startup*, not just the job.
        self.ingested += 1
        _marker.info("fake_engine_ingested")

    async def consolidate(self) -> None:
        # Leg 7's chunked walk (ADR-0106, ADR-0111). Present for `ingest`'s reason:
        # `jobs_for` builds §7's whole table before filtering it by interval, so a
        # stand-in missing a method the real façade carries fails the hub's
        # *startup* rather than only the job it would have armed.
        self.consolidated += 1
        _marker.info("fake_engine_consolidated")

    async def reconsider_notifications(self) -> int:
        # Leg 10's reconsideration drain (ADR-0130 §5), and the one job on §7's
        # table that ships **enabled** — so unlike `ingest` and `consolidate` this
        # stand-in is actually driven by the default table rather than merely
        # required to exist for it to be built.
        self.reconsidered += 1
        _marker.info("fake_engine_reconsidered")
        return 0

    async def aclose(self) -> None:
        self.closed += 1
        self.drain_phase = DrainPhase.QUIESCED
        _marker.info("fake_engine_closed")


async def _settle() -> None:
    """Park long enough for a delivered signal to reach the loop's handler.

    ``asyncio.sleep(0)`` is not enough and the reason is worth stating: asyncio
    receives signals through a self-pipe, so the handler is an I/O callback that
    needs a poll pass. A zero sleep resumes this coroutine from the *same* ready
    batch the pipe's callback was appended to, and this one runs first — so the
    hub would sail past the check under test. A short real sleep suspends on a
    timer instead, which puts the poll before the resume.
    """
    await asyncio.sleep(_SIGNAL_SETTLE_SECONDS)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointed at a private data directory that does not exist yet.

    Not created by the fixture: step 2 creating it is part of what is on test.
    """
    return Settings(data_dir=tmp_path / "hub-data")


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def sink() -> FakeTraceSink:
    """The trace sink the composition root would have opened (ADR-0119 §9).

    A fixture rather than a local, because the startup stamp writes through it and
    two tests want to read what it wrote.
    """
    return FakeTraceSink()


class _SettlingSink:
    """A conforming sink that parks long enough for a pending signal to land.

    The one thing :class:`~ai_assistant.testing.FakeTraceSink` cannot do, and it
    is :func:`_settle`'s reason applied at a second place: a signal raised from
    inside the composition root reaches the *process* at once, but the hub's
    handler is an I/O callback that needs a poll pass. A test asserting on what
    happens either side of the stop check therefore needs a real suspension
    between the two, and the stamp's own ``await`` is where one belongs.
    """

    def __init__(self) -> None:
        """Create an empty sink."""
        self.recorded: list[EvaluationTrace] = []

    async def emit(self, trace: EvaluationTrace) -> None:
        """Append ``trace``, then park for a poll pass.

        Args:
            trace: The event to record.
        """
        self.recorded.append(trace)
        await _settle()


def _composed(engine: FakeEngine, sink: TraceSink | None = None) -> Composition:
    """What the composition root returns, around a faked engine (ADR-0119 §9).

    The cast is the price of a real :class:`Composition` here rather than a
    look-alike: ``Engine`` is a concrete class and ``FakeEngine`` deliberately is
    not one, but the field the hub reads through is ``engine`` and the fields this
    lane added are the other three — a stand-in namespace would let the dataclass's
    shape drift from what the hub destructures without anything failing.

    Args:
        engine: The stand-in the hub will drive.
        sink: The trace sink the startup stamp writes through; a fresh one when
            the test does not care what it holds.

    Returns:
        A composition the hub cannot tell from the real one.
    """
    return Composition(
        engine=cast("Engine", engine),
        trace_sink=sink if sink is not None else FakeTraceSink(),
        retrieval_search_limit=5,
        conflict_search_limit=102,
    )


@pytest.fixture
def wired(
    monkeypatch: pytest.MonkeyPatch, engine: FakeEngine, sink: FakeTraceSink
) -> dict[str, list[Any]]:
    """Replace the composition root's two entry points and record their calls.

    Both are patched **where the hub looks them up**, so the substitution is of the
    seam rather than of another package's internals.
    """
    calls: dict[str, list[Any]] = {"build": [], "credentials": []}

    def _build(settings: Settings, *, data_dir: Path) -> Composition:
        calls["build"].append(data_dir)
        return _composed(engine, sink)

    def _credentials(settings: Settings) -> None:
        calls["credentials"].append(settings)

    monkeypatch.setattr(hub, "build_composition", _build)
    monkeypatch.setattr(hub, "ensure_model_credentials", _credentials)
    return calls


def _stop_after_start(
    sig: signal.Signals = signal.SIGTERM, *, times: int = 1
) -> Callable[[], None]:
    """A hook that signals this process once the hub is running.

    Safe because the hub installs its handlers before startup begins, so the
    signal lands on the hub's disposition and never on the default one.
    """

    def _send() -> None:
        for _ in range(times):
            os.kill(os.getpid(), sig)

    return _send


def _events(captured: Sequence[Mapping[str, Any]]) -> list[str]:
    return [entry["event"] for entry in captured]


def _only(captured: Sequence[Mapping[str, Any]], event: str) -> Mapping[str, Any]:
    """The one captured entry named ``event``, or a failure that says which.

    A bare ``next(...)`` would raise ``StopIteration`` inside an async test, which
    the event loop reports as an unrelated ``RuntimeError`` — a debugging tax on
    every future failure here.
    """
    matches = [entry for entry in captured if entry["event"] == event]
    assert len(matches) == 1, f"expected exactly one {event!r} in {_events(captured)}"
    return matches[0]


# --- The startup sequence (§3) ----------------------------------------------


async def test_the_data_directory_is_created_and_handed_to_the_composition_root(
    settings: Settings, wired: dict[str, list[Any]], engine: FakeEngine
) -> None:
    """Step 2 resolves the directory **once** and step 3 reuses that resolution.

    ADR-0084 §9 makes ``data_dir`` locate both the data and (later) the door, so a
    second, independent resolution of one relative or ``~``-bearing setting is two
    directories waiting to happen — and the symptom would be a missing socket
    rather than the misconfiguration it actually was.
    """
    engine.on_start = _stop_after_start()

    code = await hub.serve(settings)

    assert code == EXIT_OK
    assert settings.data_dir.is_dir()
    assert wired["build"] == [settings.data_dir]


async def test_the_lock_is_held_before_any_store_is_opened(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, engine: FakeEngine
) -> None:
    """§1 and §3 step 2, asserted behaviourally rather than by watching a spy.

    "Taken with ``flock(LOCK_EX | LOCK_NB)`` **before any store is opened**." The
    check is a real contender failing to take the lock at the exact moment the
    composition root is called — which is what a second hub would experience — so
    it cannot pass by observing the right calls in the wrong order.
    """
    observed: list[bool] = []

    def _build(settings: Settings, *, data_dir: Path) -> Composition:
        contender = InstanceLock(data_dir / LOCK_FILENAME)
        observed.append(contender.acquire())
        return _composed(engine)

    monkeypatch.setattr(hub, "build_composition", _build)
    monkeypatch.setattr(hub, "ensure_model_credentials", lambda _settings: None)
    engine.on_start = _stop_after_start()

    await hub.serve(settings)

    assert observed == [False]


async def test_readiness_is_the_last_thing_in_startup(
    settings: Settings, wired: dict[str, list[Any]], engine: FakeEngine
) -> None:
    """§3's ordering, and the constraint it hands ADR-0084.

    "Before readiness a supervisor may assume nothing but that the process
    exists." Readiness means the lock is held, every store is open and the
    at-start sweeps have run — so an event emitted before ``Engine.start()``
    returns would advertise a hub that had not finished its recovery pass, and the
    later transport lane would inherit permission to accept against a half-built
    engine.
    """
    engine.on_start = _stop_after_start()

    with structlog.testing.capture_logs() as captured:
        await hub.serve(settings)

    names = _events(captured)
    assert names.index("fake_engine_started") < names.index("hub_ready")
    assert names.index("hub_ready") < names.index("hub_shutdown_requested")


async def test_the_readiness_event_names_the_pid_the_directory_and_the_job_set(
    settings: Settings, wired: dict[str, list[Any]], engine: FakeEngine
) -> None:
    """One of the two observables §3 names, and the one needing no supervisor.

    The job set is what the scheduler actually armed, so an operator reads which
    jobs are enabled from the same line that says the hub is up. ADR-0083 §7 ships
    observation **disabled by default** precisely so "enabled" is a question worth
    asking — and asserting the default set here is what makes the omission of
    ``observation`` visible rather than incidental.
    """
    engine.on_start = _stop_after_start()

    with structlog.testing.capture_logs() as captured:
        await hub.serve(settings)

    ready = _only(captured, "hub_ready")
    assert ready["pid"] == os.getpid()
    assert ready["data_dir"] == str(settings.data_dir)
    assert ready["jobs"] == [
        "retention_purge",
        "conversation_sweep",
        "notification_reconsider",
    ]


async def test_the_configuration_is_stamped_before_the_first_operation_runs(
    settings: Settings, wired: dict[str, list[Any]], engine: FakeEngine, sink: FakeTraceSink
) -> None:
    """ADR-0119 §9's two bounds, asserted at the tighter end of the window.

    §9 requires the stamp "after the stores are open and before the API accepts a
    request", which step 6 alone would satisfy. It lands earlier than that on
    purpose, and the earlier position is what is worth pinning: read from inside
    ``Engine.start()`` — step 4, the hub's *first* operation — the trace is already
    written. So the ``CONFIGURATION`` trace is the first trace of every run, which
    is what makes §9's "a gap between a shutdown and the next configuration trace
    is a hub that was not running" exact rather than approximate.

    Asserted from inside the operation rather than by comparing two logs, because
    a successful stamp logs nothing — and a test that inferred order from the
    absence of a record would pass for a hub that never stamped at all.
    """
    at_step_four: list[int] = []
    stop = _stop_after_start()

    def _observe() -> None:
        # ``start`` is also the conversation sweep's job body, so the hook fires
        # again once the scheduler ticks; only the first call is step 4.
        at_step_four.append(len(sink.recorded))
        stop()

    engine.on_start = _observe

    assert await hub.serve(settings) == EXIT_OK
    assert at_step_four[0] == 1
    stamped = sink.recorded[0]
    assert stamped.kind is TraceKind.CONFIGURATION
    assert stamped.seam == SEAM_STARTUP


async def test_a_stop_that_lands_before_step_four_still_leaves_the_stamp(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, engine: FakeEngine
) -> None:
    """§9's requirement is unconditional once the stores are open.

    A stop signal delivered while the composition root is still building is an
    ordinary event — startup is not instantaneous, and the on-device embedder
    alone takes real time. The hub then unwinds without running step 4, which is
    ADR-0083's between-steps honouring working correctly; what must **not** ride
    on that timing is the configuration trace, because "a carrier that fires on
    every startup … cannot be forgotten" is untrue of one a signal can race.

    The stamp is therefore above the stop check rather than below it, and this is
    the branch that tells the two placements apart: the stores were open, so §9's
    condition was met, and the trace is written even though the hub goes on to
    serve nothing.
    """
    sink = _SettlingSink()

    def _build(settings: Settings, *, data_dir: Path) -> Composition:
        os.kill(os.getpid(), signal.SIGTERM)
        return _composed(engine, sink)

    monkeypatch.setattr(hub, "build_composition", _build)
    monkeypatch.setattr(hub, "ensure_model_credentials", lambda _settings: None)

    with structlog.testing.capture_logs() as captured:
        code = await hub.serve(settings)

    assert code == EXIT_OK
    assert engine.started == 0
    assert "hub_ready" not in _events(captured)
    assert [trace.kind for trace in sink.recorded] == [TraceKind.CONFIGURATION]


async def test_a_hub_whose_stamp_cannot_be_written_still_starts(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    engine: FakeEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ADR-0119 §5's subordination, reaching the sequence it is about.

    The unit-level guard is pinned in ``test_configuration.py``; what this adds is
    that nothing between the stamp and :func:`hub.serve` re-raises on its behalf.
    A hub that would not come up because its instrument could not write is the
    exact inversion §5 forbids — and it would be a *deployment* fault by §5's own
    classification, so the failure would look permanent to a supervisor.
    """

    class _RaisingSink:
        async def emit(self, trace: object) -> None:
            msg = "the trace database is locked"
            raise TraceStoreError(msg)

    def _build(settings: Settings, *, data_dir: Path) -> Composition:
        return _composed(engine, cast("TraceSink", _RaisingSink()))

    monkeypatch.setattr(hub, "build_composition", _build)
    monkeypatch.setattr(hub, "ensure_model_credentials", lambda _settings: None)
    engine.on_start = _stop_after_start()

    assert await hub.serve(settings) == EXIT_OK
    assert engine.started >= 1
    assert capsys.readouterr().err == ""


# --- Shutdown (§4) -----------------------------------------------------------


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
async def test_both_stop_signals_drain_and_exit_zero(
    sig: signal.Signals, settings: Settings, wired: dict[str, list[Any]], engine: FakeEngine
) -> None:
    """ "``SIGTERM`` and ``SIGINT`` both mean *drain and stop*, identically" (§4).

    Identical so that ``Ctrl-C`` in a foreground run behaves exactly as the
    supervisor's stop does — which is what makes a developer's experience evidence
    about production rather than a separate path nobody exercises.
    """
    engine.on_start = _stop_after_start(sig)

    code = await hub.serve(settings)

    assert code == EXIT_OK
    assert engine.closed == 1


async def test_a_second_stop_signal_does_not_escalate(
    settings: Settings, wired: dict[str, list[Any]], engine: FakeEngine
) -> None:
    """§4 refuses escalation, and the refusal is a decision rather than an omission.

    ``SIGKILL`` already provides an abrupt exit, uninterceptably. An in-process
    version would only add a second, weaker way to lose the ADR-0029 §4
    bookkeeping that graceful shutdown exists to keep — the record of *why* a step
    ended, committed under a shield exactly so a shutdown that stops waiting
    politely cannot destroy it.
    """
    engine.on_start = _stop_after_start(times=2)

    with structlog.testing.capture_logs() as captured:
        code = await hub.serve(settings)

    names = _events(captured)
    assert code == EXIT_OK
    assert names.count("hub_shutdown_requested") == 1
    assert "hub_shutdown_already_in_progress" in names
    assert engine.closed == 1


async def test_sighup_is_ignored_explicitly_and_the_hub_keeps_running(
    settings: Settings, wired: dict[str, list[Any]], engine: FakeEngine
) -> None:
    """ "A signal that silently does nothing is worse than one documented as doing
    nothing" (§4).

    The default disposition for ``SIGHUP`` is termination, so *not* installing a
    handler would not mean "ignored" — it would mean the hub dies when its
    controlling terminal goes away, which for a process designed to outlive every
    session is the opposite of what is wanted. The handler is what makes the
    documented behaviour the real one.
    """

    def _hup_then_stop() -> None:
        os.kill(os.getpid(), signal.SIGHUP)
        os.kill(os.getpid(), signal.SIGTERM)

    engine.on_start = _hup_then_stop

    with structlog.testing.capture_logs() as captured:
        code = await hub.serve(settings)

    names = _events(captured)
    assert code == EXIT_OK
    assert "hub_signal_ignored" in names
    # It kept running long enough to reach the stop it was actually given.
    assert names.index("hub_signal_ignored") < names.index("hub_shutdown_requested")


async def test_the_engine_is_closed_and_the_lock_released_on_a_clean_stop(
    settings: Settings, wired: dict[str, list[Any]], engine: FakeEngine
) -> None:
    """S2: it exits ``0`` only after a completed drain — and leaves nothing held."""
    engine.on_start = _stop_after_start()

    code = await hub.serve(settings)

    assert (code, engine.closed) == (EXIT_OK, 1)
    successor = InstanceLock(settings.data_dir / LOCK_FILENAME)
    assert successor.acquire()
    successor.release()


async def test_a_stop_during_startup_still_closes_and_releases(
    settings: Settings, wired: dict[str, list[Any]], engine: FakeEngine
) -> None:
    """A stop is honoured between steps, not deferred until the hub is serving.

    Startup is not instantaneous — the on-device embedder alone takes real time —
    so a supervisor stopping a hub that has not finished starting is an ordinary
    event, not an exotic one. Unwinding through the same ``finally`` blocks a
    normal stop uses is what keeps it from leaking a connection or the lock.
    """
    engine.on_start = _stop_after_start()
    engine.settle = True

    with structlog.testing.capture_logs() as captured:
        code = await hub.serve(settings)

    names = _events(captured)
    assert code == EXIT_OK
    # The stop landed during `start()`, so the hub never advertised itself.
    assert "hub_ready" not in names
    assert engine.closed == 1


async def test_the_scheduler_is_stopped_and_joined_before_the_engine_is_closed(
    settings: Settings, wired: dict[str, list[Any]], engine: FakeEngine
) -> None:
    """ADR-0083 §8's ordering, asserted with a job **actually in flight**.

    §8 makes this the mechanism rather than a tidiness preference:

        Service shutdown stops and joins the scheduler *before* calling
        ``Engine.aclose()``.

    A test that merely stopped an idle scheduler would pass for an implementation
    that closed the engine first, because with nothing running there is no window to
    get wrong. So the retention job is parked *inside* its body when the stop
    arrives, and the assertion is that the join reports itself before the engine
    reports closing — with the job's own body never reaching its far side, since the
    join cancels rather than waits.
    """
    running = asyncio.Event()
    finished = False

    async def parks() -> None:
        nonlocal finished
        running.set()
        await asyncio.sleep(30)
        finished = True

    engine.purge_expired = parks  # type: ignore[method-assign, assignment]

    async def stop_once_the_job_is_running() -> None:
        await asyncio.wait_for(running.wait(), timeout=5)
        os.kill(os.getpid(), signal.SIGTERM)

    with structlog.testing.capture_logs() as captured:
        async with asyncio.TaskGroup() as group:
            group.create_task(stop_once_the_job_is_running())
            code = await hub.serve(settings)

    names = _events(captured)
    assert code == EXIT_OK
    assert not finished, "the join waited for the job instead of cancelling it"
    assert names.index("hub_scheduler_stopped") < names.index("fake_engine_closed")


async def test_shutdown_reports_its_completion_its_phase_and_what_it_cost(
    settings: Settings, wired: dict[str, list[Any]], engine: FakeEngine
) -> None:
    """#559: the drain says it finished, how long it took and which phase it ended in.

    Before this the last line in the log was ``hub_shutdown_requested``, and four
    states an operator has to tell apart looked identical: phase A still within
    budget, phase B awaiting after a cancellation, phase B blocked on something that
    will never finish, and already finished. ADR-0083 §4 leaves phase B's await
    **unbounded**, so "which phase" is also "was this bounded at all".

    The phase is read from the engine rather than guessed, which is why the fake
    moves its own ``drain_phase`` inside ``aclose``: an event that hard-coded the
    happy answer would report a clean drain over a cancelled one.
    """
    engine.on_start = _stop_after_start()

    with structlog.testing.capture_logs() as captured:
        code = await hub.serve(settings)

    names = _events(captured)
    done = _only(captured, "hub_shutdown_completed")
    assert code == EXIT_OK
    assert names.index("hub_shutdown_requested") < names.index("hub_shutdown_completed")
    assert done["exit_code"] == EXIT_OK
    assert done["drain_phase"] == "phase_a_quiesced"
    assert done["jobs"] == [
        "retention_purge",
        "conversation_sweep",
        "notification_reconsider",
    ]
    for field in ("drain_seconds", "scheduler_join_seconds", "elapsed_seconds"):
        assert isinstance(done[field], float), field
        assert done[field] >= 0


async def test_a_startup_that_never_built_an_engine_reports_no_shutdown(
    settings: Settings, wired: dict[str, list[Any]]
) -> None:
    """The completion event is about a drain, so a hub with no drain stays silent.

    A contended lock never builds an engine and has nothing to drain. Emitting a
    completion event there would put a "shutdown finished" line in the log of a
    process that never started — the "crash loop wearing a diagnosis" §5 warns
    about, in miniature, and precisely the kind of noise that makes the real event
    stop being read.
    """
    settings.data_dir.mkdir(parents=True)
    holder = InstanceLock(settings.data_dir / LOCK_FILENAME)
    assert holder.acquire()

    try:
        with structlog.testing.capture_logs() as captured:
            code = await hub.serve(settings)
    finally:
        holder.release()

    assert code == EXIT_RESTART
    assert "hub_shutdown_completed" not in _events(captured)


async def test_a_drain_that_fails_still_reports_what_it_cost(
    settings: Settings, wired: dict[str, list[Any]], engine: FakeEngine
) -> None:
    """The case where an operator most needs the account is the one that went wrong.

    A closer that cannot release its connection raises out of ``aclose``. The timing
    is recorded before the exception leaves, so the event ``serve`` logs afterwards
    is about the shutdown that actually happened — carrying the classified exit code
    rather than the one the happy path would have returned.
    """

    async def refuses_to_close() -> None:
        msg = "the connection would not close"
        raise OSError(msg)

    engine.aclose = refuses_to_close  # type: ignore[method-assign]
    engine.on_start = _stop_after_start()

    with structlog.testing.capture_logs() as captured:
        code = await hub.serve(settings)

    done = _only(captured, "hub_shutdown_completed")
    assert code != EXIT_OK
    assert done["exit_code"] == code
    assert isinstance(done["drain_seconds"], float)
    # Nothing pretended the drain reached a phase it never got to.
    assert done["drain_phase"] == "not_run"


# --- Which half of the lifecycle failed (#581) -------------------------------


async def test_a_failed_drain_is_reported_as_a_shutdown_and_never_as_a_failed_start(
    settings: Settings,
    wired: dict[str, list[Any]],
    engine: FakeEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """#581: the operator is told which end of the lifecycle broke.

    A closer that will not release its connection escapes through the same
    ``except`` a startup fault does, and before this it earned the same words. "hub:
    cannot start" on a process that had been serving for three weeks sends an
    operator to look at configuration and permissions — everything except the drain
    that actually failed.

    Both halves of the assertion matter. The new wording appearing is worth little
    on its own if the old wording still appears beside it, because a message an
    operator has to reconcile against a contradicting one is not legible.
    """

    async def refuses_to_close() -> None:
        msg = "the connection would not close"
        raise OSError(msg)

    engine.aclose = refuses_to_close  # type: ignore[method-assign]
    engine.on_start = _stop_after_start()

    with structlog.testing.capture_logs() as captured:
        code = await hub.serve(settings)

    stderr = capsys.readouterr().err
    failed = _only(captured, "hub_shutdown_failed")
    assert "cannot start" not in stderr
    assert "shutdown failed while draining in-flight work" in stderr
    assert "the connection would not close" in stderr
    # The drain is where it failed, so nothing may claim the work finished.
    assert "in-flight work was not drained" in stderr
    assert failed["failed_at"] == "draining"
    assert failed["exit_code"] == code
    assert "hub_startup_failed" not in _events(captured)


async def test_a_failure_after_the_engine_is_built_is_still_reported_as_a_failed_start(
    settings: Settings,
    wired: dict[str, list[Any]],
    engine: FakeEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The discriminator is that shutdown *raised*, not that shutdown *ran*.

    §3's steps 4 to 6 sit inside the ``try`` whose ``finally`` runs the shutdown
    sequence — deliberately, so a hub killed halfway through a slow embedder load
    still closes what it opened. A store that will not open therefore produces a
    record marked ``reached``, with a shutdown that ran to completion and a startup
    fault escaping past it.

    #581 proposed keying the wording on exactly that flag, and this is the test that
    says why it cannot be: keyed on ``reached``, every one of those failures would
    be relabelled a shutdown fault, which is the same defect pointing the other way.
    """

    async def will_not_open() -> None:
        msg = "the memory store would not open"
        raise OSError(msg)

    engine.start = will_not_open  # type: ignore[method-assign]

    with structlog.testing.capture_logs() as captured:
        code = await hub.serve(settings)

    stderr = capsys.readouterr().err
    names = _events(captured)
    assert code == EXIT_RESTART
    assert "hub: cannot start: the memory store would not open" in stderr
    assert "shutdown failed" not in stderr
    assert "hub_shutdown_failed" not in names
    # The shutdown sequence did run — which is precisely why `reached` cannot be
    # the thing that chooses the wording.
    assert "hub_shutdown_completed" in names


async def test_a_shutdown_that_drained_before_it_failed_says_the_work_finished(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    wired: dict[str, list[Any]],
    engine: FakeEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ADR-0083 §4's shutdown is two-phase, so "during shutdown" is not one moment.

    A hub that drained cleanly and then could not let go of its instance lock has
    lost no work at all, and a message saying only "could not shut down" would read
    as the opposite to anyone who knows what phase B costs. So the stage is named
    and the drain's own account rides with it — which is the first question a stop
    that went wrong actually raises.
    """

    class _StuckLock(InstanceLock):
        def release(self) -> None:
            # Really released first: the failure under test is the *report*, and a
            # test that also leaked the descriptor would hold this directory for
            # the rest of the session.
            super().release()
            msg = "the lock descriptor would not close"
            raise OSError(msg)

    monkeypatch.setattr(hub, "InstanceLock", _StuckLock)
    engine.on_start = _stop_after_start()

    with structlog.testing.capture_logs() as captured:
        code = await hub.serve(settings)

    stderr = capsys.readouterr().err
    failed = _only(captured, "hub_shutdown_failed")
    assert code == EXIT_RESTART
    assert engine.closed == 1
    assert "shutdown failed while releasing the instance lock" in stderr
    assert "in-flight work had already finished on its own" in stderr
    assert failed["failed_at"] == "releasing_the_lock"
    assert failed["drain_phase"] == "phase_a_quiesced"


async def test_a_start_that_failed_and_then_failed_to_clean_up_is_still_a_failed_start(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    wired: dict[str, list[Any]],
    engine: FakeEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A ``finally`` that raises erases what it was unwinding from, and it must not.

    Python substitutes the cleanup's exception for the pending one, keeping the
    original only as ``__context__`` — which nothing on this path reads, because
    ``classify`` follows ``__cause__`` alone and deliberately so. So by the time
    ``serve`` sees anything, the hub that never opened its store looks exactly like
    a hub that served for weeks and then failed to let go of its lock.

    Both halves are asserted. Framing it as a shutdown would be #581's own defect
    mirrored — an operator told their hub stopped badly when it never came up — and
    naming only the cleanup would leave the reason the hub is down in a traceback
    nobody prints.
    """

    class _StuckLock(InstanceLock):
        def release(self) -> None:
            super().release()
            msg = "the lock descriptor would not close"
            raise OSError(msg)

    async def will_not_open() -> None:
        msg = "the memory store would not open"
        raise OSError(msg)

    monkeypatch.setattr(hub, "InstanceLock", _StuckLock)
    engine.start = will_not_open  # type: ignore[method-assign]

    with structlog.testing.capture_logs() as captured:
        await hub.serve(settings)

    stderr = capsys.readouterr().err
    failed = _only(captured, "hub_startup_failed")
    assert "shutdown failed" not in stderr
    assert "hub: cannot start: the lock descriptor would not close" in stderr
    assert "the start had already failed with: the memory store would not open" in stderr
    assert failed["replaced_cause"] == "the memory store would not open"


async def test_a_start_that_failed_and_then_failed_to_drain_is_still_a_failed_start(
    settings: Settings,
    wired: dict[str, list[Any]],
    engine: FakeEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The same substitution, one layer in: a stage of the shutdown does the erasing.

    The lock release is the *outer* cleanup and easy to see. Every stage of the
    shutdown sequence itself has the same power and runs first, so a capture point
    that sat after them would restore the erased cause on the rarer path and not on
    the commoner one — which is worse than not restoring it at all, because it looks
    fixed. Here the store will not open and the drain will not finish.
    """

    async def will_not_open() -> None:
        msg = "the memory store would not open"
        raise OSError(msg)

    async def refuses_to_close() -> None:
        msg = "the connection would not close"
        raise OSError(msg)

    engine.start = will_not_open  # type: ignore[method-assign]
    engine.aclose = refuses_to_close  # type: ignore[method-assign]

    with structlog.testing.capture_logs() as captured:
        await hub.serve(settings)

    stderr = capsys.readouterr().err
    assert "shutdown failed" not in stderr
    assert "hub: cannot start: the connection would not close" in stderr
    assert "the start had already failed with: the memory store would not open" in stderr
    assert _only(captured, "hub_startup_failed")["replaced_cause"] == (
        "the memory store would not open"
    )


async def test_a_stay_down_start_erased_by_a_cleanup_fault_still_stays_down(
    settings: Settings,
    wired: dict[str, list[Any]],
    engine: FakeEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§5's test is about the situation, not about whichever exception survived.

    "A filesystem access fault, ``78`` **wherever in startup it surfaces**" (§3 step
    3) — and it does not stop having surfaced because a ``finally`` raised over it.
    Classified on the cleanup's generic ``OSError`` alone, an ``EACCES`` that ended
    the start returns ``1`` and buys "an infinite restart loop against an unchanging
    ``EACCES``", which is §5's own name for the failure the codes exist to prevent.

    Worth stating that this is the *supervisor's* half of the same defect the rest
    of this section is about: the operator now reads the permission fault, and a
    process that printed a stay-down cause while returning a come-back code would be
    telling its two audiences different things.
    """

    async def cannot_read() -> None:
        raise PermissionError(errno.EACCES, "permission denied", str(settings.data_dir / "x.db"))

    async def refuses_to_close() -> None:
        msg = "the connection would not close"
        raise OSError(msg)

    engine.start = cannot_read  # type: ignore[method-assign]
    engine.aclose = refuses_to_close  # type: ignore[method-assign]

    code = await hub.serve(settings)

    stderr = capsys.readouterr().err
    assert code == EXIT_DEPLOYMENT
    assert "readable and writable by the user the hub runs as" in stderr
    assert "will not be fixed by restarting" in stderr


async def test_a_cleanup_fault_never_invents_a_stay_down_verdict(
    settings: Settings,
    wired: dict[str, list[Any]],
    engine: FakeEngine,
) -> None:
    """The asymmetry is the safety argument, so it is asserted rather than assumed.

    §5 puts the burden of proof on ``78``: "where a new fault does not obviously
    answer the question, the answer is ``1``: a spurious restart is recoverable and
    a spurious ``78`` is an outage." Two faults that each earn ``1`` alone must not
    add up to one that does not, or reading a second exception would have bought
    legibility at the cost of the outage §5 is most careful about.
    """

    async def a_corrupt_page() -> None:
        raise OSError(errno.EIO, "input/output error")

    async def refuses_to_close() -> None:
        msg = "the connection would not close"
        raise OSError(msg)

    engine.start = a_corrupt_page  # type: ignore[method-assign]
    engine.aclose = refuses_to_close  # type: ignore[method-assign]

    assert await hub.serve(settings) == EXIT_RESTART


async def test_a_start_that_failed_alone_does_not_have_its_cause_printed_twice(
    settings: Settings,
    wired: dict[str, list[Any]],
    engine: FakeEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The displaced cause is only ever the one a cleanup actually displaced.

    When nothing in the shutdown raises, the exception ``serve`` holds *is* the
    recorded one — so a report that printed it again under "already failed with"
    would be presenting one fact as two, on the very path where an operator is
    trying to work out how many things went wrong.
    """

    async def will_not_open() -> None:
        msg = "the memory store would not open"
        raise OSError(msg)

    engine.start = will_not_open  # type: ignore[method-assign]

    with structlog.testing.capture_logs() as captured:
        await hub.serve(settings)

    stderr = capsys.readouterr().err
    assert stderr.count("the memory store would not open") == 1
    assert "already failed with" not in stderr
    assert _only(captured, "hub_startup_failed")["replaced_cause"] is None


async def test_a_stop_that_arrived_mid_startup_still_fails_as_a_shutdown(
    settings: Settings,
    wired: dict[str, list[Any]],
    engine: FakeEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Readiness is the wrong test for which half of the lifecycle failed.

    A stop delivered during a slow engine build is an ordinary event, and the hub
    honours it between steps — so it returns through the shutdown sequence having
    never advertised itself. Nothing was in flight, nothing failed to start, and the
    hub was asked to stop: a drain that then fails is a failed shutdown, however
    plainly the hub was never running.
    """

    async def refuses_to_close() -> None:
        msg = "the connection would not close"
        raise OSError(msg)

    engine.aclose = refuses_to_close  # type: ignore[method-assign]
    engine.on_start = _stop_after_start()
    engine.settle = True

    with structlog.testing.capture_logs() as captured:
        await hub.serve(settings)

    stderr = capsys.readouterr().err
    names = _events(captured)
    assert "hub_ready" not in names
    assert "cannot start" not in stderr
    assert "shutdown failed while draining in-flight work" in stderr


async def test_a_shutdown_fault_that_stays_down_keeps_its_code_and_its_remedy(
    settings: Settings,
    wired: dict[str, list[Any]],
    engine: FakeEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§5's codes do not move; only the words around them do.

    "Would restarting, unchanged, ever succeed?" has one answer wherever the fault
    arose — an ``EACCES`` a closer hit is as unfixable by restarting as one the
    opener hit — so the classification stays in one place and keeps its verdict. The
    framing is what changes: this process is already on its way out, so the line an
    operator reads is about the *next* start rather than about a restart that is not
    being contemplated.
    """

    async def cannot_write() -> None:
        raise OSError(errno.EACCES, "permission denied", str(settings.data_dir / "memory.db"))

    engine.aclose = cannot_write  # type: ignore[method-assign]
    engine.on_start = _stop_after_start()

    code = await hub.serve(settings)

    stderr = capsys.readouterr().err
    assert code == EXIT_DEPLOYMENT
    assert "shutdown failed while draining in-flight work" in stderr
    assert "readable and writable by the user the hub runs as" in stderr
    assert "the next start will meet the same condition" in stderr


# --- Exit classification (§5, §6) -------------------------------------------


async def test_a_contended_lock_is_restartable_and_opens_no_store(
    settings: Settings, wired: dict[str, list[Any]]
) -> None:
    """§1's one deliberately counter-intuitive classification.

    A held lock always means a live holder, and a live holder is either serving —
    so the deployment is up and the loser's restart loop is harmless noise a
    supervisor backs off from — or draining, so a later attempt succeeds. Making
    it fatal would break the second case badly: phase B is unbounded, so a drain
    can outlast any retry window, and refusing to restart there leaves **no** hub
    running after the outgoing one exits cleanly, with nothing wrong to fix.
    """
    data_dir = settings.data_dir
    data_dir.mkdir(parents=True)
    holder = InstanceLock(data_dir / LOCK_FILENAME)
    assert holder.acquire()

    try:
        code = await hub.serve(settings)
    finally:
        holder.release()

    assert code == EXIT_RESTART
    assert wired["build"] == []


async def test_the_contention_diagnostic_names_the_directory_and_the_lock(
    settings: Settings, wired: dict[str, list[Any]]
) -> None:
    """§1 requires both, and requires the pid to be a hint rather than a promise."""
    data_dir = settings.data_dir
    data_dir.mkdir(parents=True)
    holder = InstanceLock(data_dir / LOCK_FILENAME)
    assert holder.acquire()

    try:
        with structlog.testing.capture_logs() as captured:
            await hub.serve(settings)
    finally:
        holder.release()

    contended = _only(captured, "hub_instance_lock_contended")
    assert contended["data_dir"] == str(data_dir)
    assert contended["lock"] == str(data_dir / LOCK_FILENAME)
    assert contended["holder_pid_hint"] == os.getpid()


async def test_a_state_fault_stays_down_and_prints_its_own_remedy(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§6 end to end: the store's refusal becomes a legible, non-restarting exit.

    This is the whole reason ADR-0083 §6 moved the embedder mismatch off
    ``MemoryStoreError``. Before, an entry point could not tell "this deployment
    cannot serve this store" from "this disk is broken" without matching on a
    message string, so under a restarting supervisor it became a crash loop with
    the reason buried in a repeating trace.
    """

    def _build(settings: Settings, *, data_dir: Path) -> Composition:
        raise IncompatibleStateError(
            "store was built with embedding_model='v1', but this embedder has 'v2'",
            expected="embedding_model='v2'",
            found="embedding_model='v1'",
            operator_action="re-embed the store, or configure the embedder it was built with",
        )

    monkeypatch.setattr(hub, "build_composition", _build)
    monkeypatch.setattr(hub, "ensure_model_credentials", lambda _settings: None)

    code = await hub.serve(settings)

    assert code == EXIT_DEPLOYMENT
    stderr = capsys.readouterr().err
    assert "re-embed the store" in stderr
    assert "will not be fixed by restarting" in stderr


async def test_a_missing_credential_stays_down_before_any_store_is_opened(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """#530, closed at the only layer that can see it.

    Left unchecked the hub would start, signal ready, look healthy to every
    supervisor and monitor, and fail hours later on a user's first real request —
    the exact inverse of the legibility property §6 establishes. It is a
    deployment fault: no restart produces a credential.

    That it runs **above** the composition root's disk line is the second half.
    Nothing should open seven databases to discover a variable is unset.
    """
    built: list[Path] = []

    def _build(settings: Settings, *, data_dir: Path) -> Composition:
        built.append(data_dir)
        return _composed(FakeEngine())

    def _credentials(settings: Settings) -> None:
        msg = "model spec 'anthropic:x' names provider 'anthropic', for which this deployment holds no credential"  # noqa: E501
        raise ConfigurationError(msg)

    monkeypatch.setattr(hub, "build_composition", _build)
    monkeypatch.setattr(hub, "ensure_model_credentials", _credentials)

    code = await hub.serve(settings)

    assert code == EXIT_DEPLOYMENT
    assert built == []
    assert "no credential" in capsys.readouterr().err


async def test_an_unexpected_fault_comes_back_and_asks_nothing_of_anyone(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """§5's default, and the silence that goes with it.

    A restartable fault prints no operator action, because none is being asked.
    Inventing an instruction there would be "a crash loop wearing a diagnosis" in
    the other direction — an operator told to act on something that will clear by
    itself.
    """

    def _build(settings: Settings, *, data_dir: Path) -> Composition:
        msg = "a corrupt page"
        raise RuntimeError(msg)

    monkeypatch.setattr(hub, "build_composition", _build)
    monkeypatch.setattr(hub, "ensure_model_credentials", lambda _settings: None)

    code = await hub.serve(settings)

    assert code == EXIT_RESTART
    stderr = capsys.readouterr().err
    assert "a corrupt page" in stderr
    assert "will not be fixed by restarting" not in stderr


async def test_the_lock_is_released_when_startup_fails(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hub that could not start must not be what stops the next one starting.

    Without this the first failure would be permanent for as long as the process
    lived, and — since contention is classified as restartable — a supervisor
    would restart into a directory its own predecessor was still holding.
    """

    def _build(settings: Settings, *, data_dir: Path) -> Composition:
        msg = "no"
        raise RuntimeError(msg)

    monkeypatch.setattr(hub, "build_composition", _build)
    monkeypatch.setattr(hub, "ensure_model_credentials", lambda _settings: None)

    await hub.serve(settings)

    successor = InstanceLock(settings.data_dir / LOCK_FILENAME)
    assert successor.acquire()
    successor.release()


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses directory permissions")
async def test_an_unwritable_data_directory_stays_down(
    settings: Settings, tmp_path: Path, wired: dict[str, list[Any]]
) -> None:
    """§3 step 2's writability check, and §5's reasoning for the code it earns.

    "A directory the process may not write into does not become writable by being
    opened again, and mapping it to ``1`` buys an infinite restart loop against an
    unchanging ``EACCES``."
    """
    sealed = tmp_path / "sealed"
    sealed.mkdir()
    sealed.chmod(0o500)
    unwritable = Settings(data_dir=sealed / "hub-data")

    try:
        code = await hub.serve(unwritable)
    finally:
        sealed.chmod(0o700)

    assert code == EXIT_DEPLOYMENT
    assert wired["build"] == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root satisfies every ownership check")
async def test_a_world_writable_data_directory_stays_down_before_the_lock(
    settings: Settings, tmp_path: Path, wired: dict[str, list[Any]]
) -> None:
    """ADR-0084 §1's directory conditions, wired into step 2 and exiting 78.

    Order is the substance: the refusal has to land **before** the lock is taken
    and before any store is opened, because both of those create files in the
    directory whose safety is in question. A hub that validated afterwards would
    have written the lock — and, later, the socket — into a directory another
    local user can replace entries in.
    """
    exposed = tmp_path / "exposed"
    exposed.mkdir()
    exposed.chmod(0o777)
    unsafe = Settings(data_dir=exposed)

    try:
        code = await hub.serve(unsafe)
    finally:
        exposed.chmod(0o700)

    assert code == EXIT_DEPLOYMENT
    assert wired["build"] == []
    assert not (exposed / LOCK_FILENAME).exists()


async def test_a_transient_filesystem_fault_still_comes_back(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other side of the same boundary: a full disk is not a deployment mistake."""

    def _build(settings: Settings, *, data_dir: Path) -> Composition:
        raise OSError(errno.ENOSPC, "no space left on device")

    monkeypatch.setattr(hub, "build_composition", _build)
    monkeypatch.setattr(hub, "ensure_model_credentials", lambda _settings: None)

    assert await hub.serve(settings) == EXIT_RESTART


# --- The entry point (§3 step 1) --------------------------------------------


def test_main_reports_a_settings_failure_as_a_deployment_fault(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Step 1, and the reason it lives outside :func:`serve`.

    Until settings load there is no log level to configure logging with, so this
    is the one failure reported before the process has a configured logger at all
    — which is exactly why §5 requires stderr as well as the log.
    """

    def _load() -> Settings:
        msg = "invalid configuration: unknown log level 'EROR'"
        raise ConfigurationError(msg)

    monkeypatch.setattr(hub, "load_settings", _load)

    code = hub.main()

    assert code == EXIT_DEPLOYMENT
    stderr = capsys.readouterr().err
    assert "unknown log level" in stderr
    assert "will not be fixed by restarting" in stderr


# --- ADR-0124 §2: the remote listener is off unless it is configured on ------


async def test_a_hub_with_no_remote_configuration_binds_only_the_loopback_socket(
    settings: Settings, wired: dict[str, list[Any]], engine: FakeEngine
) -> None:
    """ADR-0124 §2: "a hub with no remote-listener configuration binds only ADR-0084
    §1's loopback socket, and the loopback socket is bound whether or not the remote
    listener is".

    Asserted through the readiness event, which is where an operator reads it, and
    through the enrolment record's *absence*: a hub that built the apparatus anyway
    would need an overlay agent it is not running, and would leave a database in the
    data directory for a door it never opened.
    """
    engine.on_start = _stop_after_start()

    with structlog.testing.capture_logs() as captured:
        code = await hub.serve(settings)

    assert code == EXIT_OK
    ready = _only(captured, "hub_ready")
    assert ready["remote"] is None
    assert "hub_remote_listening" not in _events(captured)
    assert not (settings.data_dir / "devices.db").exists()


async def test_a_configured_hub_that_cannot_ask_its_agent_stays_down(
    settings: Settings,
    wired: dict[str, list[Any]],
    engine: FakeEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured remote listener whose overlay agent is absent is a deployment
    fault, not a hub that quietly serves loopback alone.

    ADR-0124 §6 discloses the hub's own overlay identity at enrolment and §4 reads a
    device's at admission; neither can happen without the agent. Coming up anyway
    would be the hub silently ignoring the configuration the operator set, which is
    ADR-0083's ruling 4 failure — so it is a ``ConfigurationError`` and exit 78,
    "this will not be fixed by restarting".
    """
    from ai_assistant.service.overlay import (  # noqa: PLC0415 - one call site
        OverlayIdentityUnavailableError,
        TailscaleAgent,
    )

    async def _absent(self: TailscaleAgent) -> Any:
        del self
        msg = "the overlay agent is not running"
        raise OverlayIdentityUnavailableError(msg)

    monkeypatch.setattr(TailscaleAgent, "hub_identity", _absent)
    configured = settings.model_copy(update={"hub_remote_address": "100.64.0.9"})

    code = await hub.serve(configured)

    assert code == EXIT_DEPLOYMENT


async def test_a_hub_whose_control_socket_will_not_bind_serves_no_remote_request(
    settings: Settings,
    wired: dict[str, list[Any]],
    engine: FakeEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0083 §14.2 across *several* doors: every bind first, then any accept.

    A hub that opened one door and then failed to bind the next would have served a
    request during a startup that never reached readiness — the request carried out
    by a hub that does not exist. The failure is injected at the last bind, which is
    the position that discriminates: an implementation opening doors as it goes
    passes every other startup test and fails only here.
    """
    from ai_assistant.service import admin as admin_module  # noqa: PLC0415 - one call site
    from ai_assistant.service import overlay as overlay_module  # noqa: PLC0415 - one call site
    from ai_assistant.service import remote as remote_module  # noqa: PLC0415 - one call site

    served: list[str] = []

    async def _reported() -> Any:
        return overlay_module.HubOverlayIdentity(
            identity="nHUB", addresses=frozenset({"127.0.0.1"})
        )

    async def _no_bind(self: admin_module.AdminListener) -> None:
        del self
        raise OSError(errno.EADDRINUSE, "address already in use")

    async def _note_serving(self: remote_module.RemoteListener) -> None:
        served.append(f"{self.address}:{self.port}")

    monkeypatch.setattr(overlay_module.TailscaleAgent, "hub_identity", lambda self: _reported())
    monkeypatch.setattr(admin_module.AdminListener, "start", _no_bind)
    monkeypatch.setattr(remote_module.RemoteListener, "begin_serving", _note_serving)
    configured = settings.model_copy(
        update={"hub_remote_address": "127.0.0.1", "hub_remote_port": 0}
    )

    code = await hub.serve(configured)

    assert code != EXIT_OK
    assert served == []


async def test_the_configured_agent_socket_reaches_the_agent_the_hub_builds(
    settings: Settings,
    wired: dict[str, list[Any]],
    engine: FakeEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#918: the seam ADR-0124 §4 designs as substitutable is reachable from
    configuration.

    ``local_agent`` has always accepted a socket path and the composition root
    always passed none, so the whole remote surface had no producer an operator
    could point anywhere — §§6-8 were exercisable only from outside the
    application. This asserts the one link that was missing: what
    ``hub_overlay_agent_socket`` names is what the hub asks.

    The agent is then made to refuse, so the assertion is about the *wiring* and
    the hub still reaches a deterministic exit rather than standing up the remote
    apparatus this test does not examine.
    """
    from ai_assistant.service.overlay import (  # noqa: PLC0415 - one call site
        OverlayIdentityUnavailableError,
    )

    asked: list[str | None] = []

    class _Recording:
        async def hub_identity(self) -> Any:
            msg = "the overlay agent is not running"
            raise OverlayIdentityUnavailableError(msg)

    def _record(socket_path: str | None = None) -> Any:
        asked.append(socket_path)
        return _Recording()

    monkeypatch.setattr(hub, "local_agent", _record)
    configured = settings.model_copy(
        update={
            "hub_remote_address": "100.64.0.9",
            "hub_overlay_agent_socket": "/run/qa/tailscaled.sock",
        }
    )

    code = await hub.serve(configured)

    assert code == EXIT_DEPLOYMENT
    assert asked == ["/run/qa/tailscaled.sock"]


async def test_a_hub_with_no_configured_agent_socket_still_asks_for_the_defaults(
    settings: Settings,
    wired: dict[str, list[Any]],
    engine: FakeEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The discriminating half: unset means unset, not some new value.

    Without this the test above would pass for a hub that always passed a path,
    and the "unset changes nothing" claim that makes the field additive would be
    untested.
    """
    from ai_assistant.service.overlay import (  # noqa: PLC0415 - one call site
        OverlayIdentityUnavailableError,
    )

    asked: list[str | None] = []

    class _Recording:
        async def hub_identity(self) -> Any:
            msg = "the overlay agent is not running"
            raise OverlayIdentityUnavailableError(msg)

    def _record(socket_path: str | None = None) -> Any:
        asked.append(socket_path)
        return _Recording()

    monkeypatch.setattr(hub, "local_agent", _record)
    configured = settings.model_copy(update={"hub_remote_address": "100.64.0.9"})

    code = await hub.serve(configured)

    assert code == EXIT_DEPLOYMENT
    assert asked == [None]
