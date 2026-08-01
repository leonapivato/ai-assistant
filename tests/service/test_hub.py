"""The resident process: how it starts, what it refuses, how it stops (ADR-0083).

The engine is faked here, deliberately and by the project's own rule that a
subsystem is tested against its contract and stood in for elsewhere. Nothing below
is about what an engine does; it is about **order**, **classification** and
**cleanup** — the three things a resident process gets wrong invisibly and a CLI
never had to get right at all.

Order, because ADR-0083 §3 makes startup a fixed sequence in which no step begins
before the previous one has succeeded, and every one of those orderings is
load-bearing: the lock before any store, so exclusivity is not a race; readiness
last, so nothing observes a half-built engine; and the scheduler joined before
``Engine.aclose()`` (§8), which is expressed in code position here because the
scheduler itself is a later lane.

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
from typing import TYPE_CHECKING, Any

import pytest
import structlog

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ConfigurationError, IncompatibleStateError
from ai_assistant.service import hub
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART
from ai_assistant.service.lock import LOCK_FILENAME, InstanceLock

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

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
        #: Run inside ``start()``. Tests use it to signal the process at a point
        #: where the hub's own handlers are certainly installed.
        self.on_start: Callable[[], None] | None = None
        #: Whether ``start()`` parks after the hook. Off by default, so a signal
        #: raised there is handled at the hub's *next* suspension — which is
        #: ``stop.wait()``, i.e. after readiness. On, the signal lands while
        #: startup is still running, which is the other case worth testing.
        self.settle = False

    async def start(self) -> None:
        self.started += 1
        _marker.info("fake_engine_started")
        if self.on_start is not None:
            self.on_start()
        if self.settle:
            await _settle()

    async def aclose(self) -> None:
        self.closed += 1
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
def wired(monkeypatch: pytest.MonkeyPatch, engine: FakeEngine) -> dict[str, list[Any]]:
    """Replace the composition root's two entry points and record their calls.

    Both are patched **where the hub looks them up**, so the substitution is of the
    seam rather than of another package's internals.
    """
    calls: dict[str, list[Any]] = {"build": [], "credentials": []}

    def _build(settings: Settings, *, data_dir: Path) -> FakeEngine:
        calls["build"].append(data_dir)
        return engine

    def _credentials(settings: Settings) -> None:
        calls["credentials"].append(settings)

    monkeypatch.setattr(hub, "build_engine", _build)
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

    def _build(settings: Settings, *, data_dir: Path) -> FakeEngine:
        contender = InstanceLock(data_dir / LOCK_FILENAME)
        observed.append(contender.acquire())
        return engine

    monkeypatch.setattr(hub, "build_engine", _build)
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

    The job set is empty because the scheduler (§§7-9) is a lane behind this one.
    Reporting it as a field rather than omitting it is the point: when jobs exist,
    an operator reads which ones are enabled from the same line, and ADR-0083 §7
    ships observation disabled by default precisely so that "enabled" is a
    question worth asking.
    """
    engine.on_start = _stop_after_start()

    with structlog.testing.capture_logs() as captured:
        await hub.serve(settings)

    ready = _only(captured, "hub_ready")
    assert ready["pid"] == os.getpid()
    assert ready["data_dir"] == str(settings.data_dir)
    assert ready["jobs"] == []


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

    def _build(settings: Settings, *, data_dir: Path) -> FakeEngine:
        raise IncompatibleStateError(
            "store was built with embedding_model='v1', but this embedder has 'v2'",
            expected="embedding_model='v2'",
            found="embedding_model='v1'",
            operator_action="re-embed the store, or configure the embedder it was built with",
        )

    monkeypatch.setattr(hub, "build_engine", _build)
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
    Nothing should open five databases to discover a variable is unset.
    """
    built: list[Path] = []

    def _build(settings: Settings, *, data_dir: Path) -> FakeEngine:
        built.append(data_dir)
        return FakeEngine()

    def _credentials(settings: Settings) -> None:
        msg = "model spec 'anthropic:x' names provider 'anthropic', for which this deployment holds no credential"  # noqa: E501
        raise ConfigurationError(msg)

    monkeypatch.setattr(hub, "build_engine", _build)
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

    def _build(settings: Settings, *, data_dir: Path) -> FakeEngine:
        msg = "a corrupt page"
        raise RuntimeError(msg)

    monkeypatch.setattr(hub, "build_engine", _build)
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

    def _build(settings: Settings, *, data_dir: Path) -> FakeEngine:
        msg = "no"
        raise RuntimeError(msg)

    monkeypatch.setattr(hub, "build_engine", _build)
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

    def _build(settings: Settings, *, data_dir: Path) -> FakeEngine:
        raise OSError(errno.ENOSPC, "no space left on device")

    monkeypatch.setattr(hub, "build_engine", _build)
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
