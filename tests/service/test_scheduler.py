"""The hub's internal scheduler (ADR-0083 §§7-9).

Four properties carry the ADR and everything here is one of them.

**Completion-scheduled, not rate-scheduled.** A job's next run is armed from its
*completion*, which is what makes it structurally unable to overlap itself — and
the only way to prove that is with a job whose body outlasts its own interval, so
the two schedules give visibly different answers rather than the same one.

**Serial.** A long job delays its siblings and nothing runs concurrently, so there
is never a question of two jobs contending on one store's connection.

**A failing job never takes the process down** — with one exception, and the
exception is the interesting half: the ``RuntimeError`` ``_reject_if_closing``
raises means *stop*, and every other ``RuntimeError`` still means *retry*. A test
that only checked the first would pass for an implementation that swallowed every
bug as a clean exit, so both are asserted.

**Stopping is prompt.** ``aclose`` cancels rather than waits, because the join
happens before phase A's budget starts (ADR-0083 §8), and cancelling is safe only
because a job's underlying work is the engine's tracked, shielded task.

Timings here are short real durations rather than a virtual clock: ``asyncio``
offers no clock to fake, and the margins below are chosen so the property under
test is what fails, not the machine's mood.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
import structlog

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.orchestration.engine import ENGINE_SHUTTING_DOWN, Engine
from ai_assistant.service.scheduler import Job, Scheduler, jobs_for

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from pathlib import Path

#: Short enough to keep the suite quick, long enough that a scheduler which
#: re-armed from a job's *start* would land visibly inside a running job.
_TICK = timedelta(milliseconds=40)


def _job(name: str, body: Callable[[], Awaitable[object]], *, every: timedelta = _TICK) -> Job:
    return Job(name=name, interval=every, run=body)


def _events(captured: Sequence[Mapping[str, Any]]) -> list[str]:
    return [str(entry["event"]) for entry in captured]


async def _drive(scheduler: Scheduler, *, until: asyncio.Event) -> None:
    """Start the scheduler, wait for the test's own signal, then stop and join."""
    scheduler.start()
    try:
        await asyncio.wait_for(until.wait(), timeout=5)
    finally:
        await scheduler.aclose()


# --- The job table (§7) ------------------------------------------------------


async def test_the_job_table_is_the_adr_s_three_in_the_adr_s_order(tmp_path: Path) -> None:
    """§7's table, built over a real engine, with observation disabled by default.

    A real ``Engine`` rather than a stand-in, because the claim being made is about
    *which methods the jobs are bound to* — and a fake with the right attribute
    names would satisfy that assertion while proving nothing about the façade the
    hub actually holds.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        jobs = jobs_for(engine, Settings())

        assert [job.name for job in jobs] == ["retention_purge", "conversation_sweep"]
        assert [job.interval for job in jobs] == [timedelta(hours=1), timedelta(hours=1)]
    finally:
        await engine.aclose()


async def test_the_retention_job_is_the_engine_method_the_sweep_guard_permits(
    tmp_path: Path,
) -> None:
    """The job table and ``tests/app``'s static guard have to name the same thing.

    That guard pins ``Engine._purge_expired`` as the only place either Tier 1 store
    may be swept (ADR-0083 §11), and it would pass just as happily over a
    ``_purge_expired`` nobody ever called — which is precisely the state ADR-0078
    §10 item 8 left behind and #493 exists to end. Nothing mechanical connects "the
    only permitted sweeper" to "something actually calls it", so the link is
    asserted here: the armed job **is** the public method that delegates into that
    permitted body, by identity and not by name.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        jobs = {job.name: job for job in jobs_for(engine, Settings())}

        assert jobs["retention_purge"].run == engine.purge_expired
        # ADR-0076 §5: the scheduler "inherits this method unchanged" — the
        # conversation sweep is `Engine.start()` itself, not a copy of its pair.
        assert jobs["conversation_sweep"].run == engine.start
    finally:
        await engine.aclose()


async def test_a_disabled_job_is_absent_from_the_table_not_present_and_skipped(
    tmp_path: Path,
) -> None:
    """ "Disabled" is ``None`` and it means *not armed* (§7).

    ``hub_ready``'s ``jobs`` field is read by an operator as "these are running", so
    a disabled job that stayed in the table and was skipped each tick would make
    that line a lie. Enabling observation is the other direction of the same claim.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        none_at_all = jobs_for(
            engine,
            Settings(retention_purge_interval=None, conversation_sweep_interval=None),
        )
        assert none_at_all == ()

        with_observation = jobs_for(engine, Settings(observation_interval=timedelta(hours=6)))
        assert [job.name for job in with_observation] == [
            "retention_purge",
            "conversation_sweep",
            "observation",
        ]
        assert with_observation[2].run == engine.observe
    finally:
        await engine.aclose()


@pytest.mark.parametrize("bad", [timedelta(0), timedelta(seconds=-1)])
def test_a_job_refuses_a_non_positive_interval(bad: timedelta) -> None:
    """The guard restated where the invariant is used, not only at load (§7).

    On a completion-scheduled loop a zero interval makes a job due again the instant
    it finishes, which turns a retention purge into a hot loop against SQLite. A
    ``Scheduler`` built in a test, or from a future table that reads no setting,
    must not be able to arm one.
    """
    with pytest.raises(ValueError, match="strictly positive interval"):
        _job("bad", _nothing, every=bad)


async def _nothing() -> None:
    return None


# --- The loop (§7, §9) -------------------------------------------------------


async def test_every_job_runs_on_the_first_tick_in_the_table_s_order() -> None:
    """Jobs are due at start, and the fixed order is the table's.

    Due at start rather than one interval out, deliberately: a hub restarted more
    often than its longest interval would otherwise never sweep at all, and the
    retention purge is exactly the job whose absence ADR-0078 §1's exposure cap is
    measured by (#493).
    """
    ran: list[str] = []
    both = asyncio.Event()

    async def record(name: str) -> None:
        ran.append(name)
        if len(ran) >= 2:
            both.set()

    scheduler = Scheduler(
        [
            _job("first", lambda: record("first"), every=timedelta(hours=1)),
            _job("second", lambda: record("second"), every=timedelta(hours=1)),
        ]
    )
    await _drive(scheduler, until=both)

    assert ran == ["first", "second"]


async def test_a_job_is_re_armed_from_its_completion_not_from_its_start() -> None:
    """§7's fixed delay, proven with a job that outlasts its own interval.

    "A fixed-rate schedule would let a long walk be re-entered by the next tick; a
    fixed delay after completion cannot." The body sleeps for **four** intervals, so
    under fixed-rate scheduling the job would be due the instant it returned and the
    gap between one completion and the next start would be ~0. Under fixed delay it
    is a whole interval. Asserting the *gap* rather than the period is what makes
    the two answers different rather than merely differently rounded.
    """
    loop = asyncio.get_running_loop()
    starts: list[float] = []
    ends: list[float] = []
    twice = asyncio.Event()

    async def slow() -> None:
        starts.append(loop.time())
        await asyncio.sleep(_TICK.total_seconds() * 4)
        ends.append(loop.time())
        if len(starts) >= 2:
            twice.set()

    await _drive(Scheduler([_job("slow", slow)]), until=twice)

    assert len(starts) == 2
    gap = starts[1] - ends[0]
    # A fixed-*rate* loop yields a gap of ~0 here, because the job is already
    # overdue by three intervals when it finishes. 0.75 of an interval leaves room
    # for scheduling jitter without admitting that answer.
    assert gap >= _TICK.total_seconds() * 0.75, f"re-armed from the start, not the end: {gap}s"


async def test_jobs_never_overlap_each_other() -> None:
    """Serial, in §7's words: "one at a time".

    Each body brackets a suspension point, so a concurrent loop would interleave the
    markers. Serialising is what "removes any question of two jobs contending on one
    store's connection", and it is also why starvation is accepted rather than
    engineered away — a property only worth accepting if it is actually there.
    """
    marks: list[str] = []
    enough = asyncio.Event()

    def body(name: str) -> Callable[[], Awaitable[None]]:
        async def run() -> None:
            marks.append(f"{name}-in")
            await asyncio.sleep(_TICK.total_seconds() / 2)
            marks.append(f"{name}-out")
            if len(marks) >= 8:
                enough.set()

        return run

    await _drive(
        Scheduler([_job("a", body("a")), _job("b", body("b"))]),
        until=enough,
    )

    pairs = [marks[i : i + 2] for i in range(0, len(marks) - 1, 2)]
    assert all(pair[0].endswith("-in") and pair[1].endswith("-out") for pair in pairs), marks
    assert all(pair[0][0] == pair[1][0] for pair in pairs), marks


async def test_a_failing_job_is_logged_with_its_class_and_retried() -> None:
    """§7: "A failing job never takes the process down."

    Logged with its class (ADR-0004 §5) and retried at its next due instant. Nothing
    in the job list is load-bearing for correctness, so escalating a sweep failure to
    a process exit would trade a harmless backlog for an outage — and a sibling job
    must keep running too, or one broken sweep would silently stop the rest.
    """
    attempts = 0
    sibling = 0
    twice = asyncio.Event()

    async def always_fails() -> None:
        nonlocal attempts
        attempts += 1
        if attempts >= 2:
            twice.set()
        msg = "the store is on fire"
        raise ZeroDivisionError(msg)

    async def healthy() -> None:
        nonlocal sibling
        sibling += 1

    with structlog.testing.capture_logs() as captured:
        await _drive(
            Scheduler([_job("broken", always_fails), _job("healthy", healthy)]),
            until=twice,
        )

    assert attempts >= 2, "the job was not retried after failing"
    assert sibling >= 1, "a failing job stopped its sibling"
    failures = [entry for entry in captured if entry["event"] == "hub_scheduler_job_failed"]
    assert failures, _events(captured)
    assert failures[0]["job"] == "broken"
    assert failures[0]["error_class"] == "ZeroDivisionError"
    assert failures[0]["cause"] == "the store is on fire"


async def test_a_job_s_result_is_never_logged() -> None:
    """ADR-0004 §5: the operational log carries no Tier 0/1 content.

    The scheduler is generic over jobs and cannot know which results are safe to
    render — an ``ObservationReport`` names beliefs — so it renders none of them. A
    completion line says the job's name and how long it took, and nothing else.
    """
    done = asyncio.Event()

    async def returns_something_sensitive() -> str:
        done.set()
        return "the user's mother is called Marion"

    with structlog.testing.capture_logs() as captured:
        await _drive(Scheduler([_job("leaky", returns_something_sensitive)]), until=done)

    completed = [entry for entry in captured if entry["event"] == "hub_scheduler_job_completed"]
    assert completed, _events(captured)
    assert set(completed[0]) >= {"job", "elapsed_seconds"}
    assert not any("Marion" in str(value) for entry in captured for value in entry.values())


# --- Stopping (§8) -----------------------------------------------------------


async def test_the_engine_s_shutting_down_error_stops_the_loop() -> None:
    """§8's belt and braces: that ``RuntimeError`` means stop, not retry.

    It closes the window between ``Engine.aclose()`` setting ``_closing`` and this
    loop being joined. A scheduler that logged it and retried would spend that
    window failing once per tick against an engine that will never accept work
    again.

    The loop must end **on its own** — nothing cancels it here — and the job later
    in the table must not run in the same pass, because the engine that refused the
    first will refuse it too.
    """
    later = 0

    async def refuses() -> None:
        raise RuntimeError(ENGINE_SHUTTING_DOWN)

    async def after() -> None:
        nonlocal later
        later += 1

    scheduler = Scheduler([_job("refused", refuses), _job("after", after)])
    with structlog.testing.capture_logs() as captured:
        scheduler.start()
        await asyncio.sleep(_TICK.total_seconds() * 3)
        # Ended on its own: nobody cancelled it, and it is not still sleeping
        # towards the next tick.
        assert scheduler._task is not None
        assert scheduler._task.done()
        assert not scheduler._task.cancelled()
        await scheduler.aclose()

    assert later == 0, "the loop kept going after the engine refused work"
    assert "hub_scheduler_stopping" in _events(captured)
    assert "hub_scheduler_job_failed" not in _events(captured)


async def test_any_other_runtime_error_is_a_failure_and_not_a_stop() -> None:
    """The discriminating half: only *that* message stops the loop.

    Treating every ``RuntimeError`` as a shutdown would turn a real bug — a loop
    already running, a re-entered store — into a silent clean exit, which is the
    failure mode a resident process can least afford. The message is matched against
    the engine's own constant, so the two sides cannot drift.
    """
    attempts = 0
    twice = asyncio.Event()

    async def buggy() -> None:
        nonlocal attempts
        attempts += 1
        if attempts >= 2:
            twice.set()
        msg = "Event loop is closed"
        raise RuntimeError(msg)

    with structlog.testing.capture_logs() as captured:
        await _drive(Scheduler([_job("buggy", buggy)]), until=twice)

    assert attempts >= 2, "an unrelated RuntimeError stopped the loop"
    assert "hub_scheduler_stopping" not in _events(captured)
    failed = [entry for entry in captured if entry["event"] == "hub_scheduler_job_failed"]
    assert failed, _events(captured)
    assert failed[0]["error_class"] == "RuntimeError"


async def test_aclose_joins_promptly_even_while_a_job_is_running() -> None:
    """The join precedes phase A's budget, so it cannot wait for a long job (§8).

    Cancelling is safe precisely because a job is a public engine call:
    ``Engine._tracked`` runs the underlying work as a shielded task the engine
    holds, so cancelling this loop abandons only the *await* and the drain that
    follows still waits for the work (ADR-0042 §2, ADR-0054). This asserts the
    promptness half — that ``aclose`` does not sit through a job that would outlast
    any sensible stop timeout.
    """
    entered = asyncio.Event()
    finished = False

    async def forever() -> None:
        nonlocal finished
        entered.set()
        await asyncio.sleep(30)
        finished = True

    scheduler = Scheduler([_job("forever", forever)])
    scheduler.start()
    await asyncio.wait_for(entered.wait(), timeout=5)

    await asyncio.wait_for(scheduler.aclose(), timeout=1)

    assert not finished
    assert not scheduler.running


async def test_aclose_is_idempotent_and_safe_before_a_start() -> None:
    """Shutdown runs it unconditionally from a ``finally``, so both must be no-ops."""
    scheduler = Scheduler([_job("unused", _nothing)])
    await scheduler.aclose()  # never started
    scheduler.start()
    await scheduler.aclose()
    await scheduler.aclose()  # twice


async def test_starting_twice_is_refused() -> None:
    """Two loops over one engine would run every job twice.

    Which is exactly the self-overlap §7's completion-scheduling exists to make
    impossible, arrived at from the other direction.
    """
    scheduler = Scheduler([_job("once", _nothing)])
    scheduler.start()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            scheduler.start()
    finally:
        await scheduler.aclose()


async def test_an_empty_table_starts_and_stops_without_spinning() -> None:
    """A deployment that disabled every job asked for a scheduler that does nothing.

    It must not become a loop with no sleep in it, which is what a table-driven
    ``min()`` over an empty set would be if the emptiness were not handled.
    """
    scheduler = Scheduler([])
    scheduler.start()
    await asyncio.sleep(0)
    assert scheduler.job_names == ()
    await asyncio.wait_for(scheduler.aclose(), timeout=1)


async def test_a_loop_that_fails_outright_is_logged_rather_than_raised() -> None:
    """Shutdown must not be derailed by the thing it is shutting down.

    Jobs cannot reach here — ``_run_job`` absorbs them — so a loop that ends with an
    exception is a fault in the loop itself, and it is worth seeing rather than
    worth raising into a ``finally`` that still has an engine to close.
    """

    class _Exploding(Scheduler):
        async def _run(self) -> None:
            msg = "the loop itself broke"
            raise ValueError(msg)

    scheduler = _Exploding([_job("unused", _nothing)])
    with structlog.testing.capture_logs() as captured:
        scheduler.start()
        await asyncio.sleep(0)
        await scheduler.aclose()

    failure = [entry for entry in captured if entry["event"] == "hub_scheduler_loop_failed"]
    assert failure, _events(captured)
    assert failure[0]["error_class"] == "ValueError"


async def test_a_job_calling_a_closing_engine_gets_the_shared_message(tmp_path: Path) -> None:
    """The constant the scheduler matches is the one the engine actually raises.

    Two spellings of one message is a seam that fails silently: the scheduler would
    log a shutdown as a job failure and retry against an engine that will never
    accept work again. Asserted end to end against the real façade rather than
    against the constant, because comparing the constant to itself proves nothing.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    await engine.aclose()

    with pytest.raises(RuntimeError) as raised:
        await engine.purge_expired()

    assert str(raised.value) == ENGINE_SHUTTING_DOWN
    assert isinstance(engine, Engine)
