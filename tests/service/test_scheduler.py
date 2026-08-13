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
import math
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import TYPE_CHECKING, Any

import pytest
import structlog
from pydantic import ValidationError

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.protocols import AssistantEngine
from ai_assistant.core.types import GrantScope
from ai_assistant.orchestration.engine import ENGINE_SHUTTING_DOWN, Engine
from ai_assistant.readers import CALENDAR_READER_NAME, EMAIL_READER_NAME
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


async def test_the_job_table_is_the_adr_s_enabled_defaults_in_the_adr_s_order(
    tmp_path: Path,
) -> None:
    """§7's table, built over a real engine, with observation disabled by default.

    A real ``Engine`` rather than a stand-in, because the claim being made is about
    *which methods the jobs are bound to* — and a fake with the right attribute
    names would satisfy that assertion while proving nothing about the façade the
    hub actually holds.

    **Three enabled by default, and the third's default is minutes** (ADR-0130 §5):
    the reconsideration job ships enabled because "with no producers it rules
    nothing, and a held record whose window has passed is the one thing this ADR
    cannot leave to a later act", and it is the one job here whose latency a user
    can feel.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        jobs = jobs_for(engine, Settings())

        assert [job.name for job in jobs] == [
            "retention_purge",
            "conversation_sweep",
            "notification_reconsider",
        ]
        assert [job.interval for job in jobs] == [
            timedelta(hours=1),
            timedelta(hours=1),
            timedelta(minutes=5),
        ]
    finally:
        await engine.aclose()


async def test_the_reconsideration_job_is_the_concrete_engine_s_maintenance_call(
    tmp_path: Path,
) -> None:
    """ADR-0130 §5 and §9, asserted by identity rather than by name.

    §9 is explicit that reconsideration "is added to the concrete engine's
    maintenance surface and to no Protocol" and that it "is **not** a member of
    ``AssistantEngine``: no client asks for it and no interface adapter may drive
    it". §5 then requires exactly one caller: a job on this table whose body is
    that engine call and **which holds no store** — so ADR-0083 §7's "no job gets
    new store surface" and §8's "every job is a bound public engine method" both
    hold unchanged. Binding the job to the method object is what makes that
    checkable; a name would pass over a job that reached the store directly.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        jobs = {job.name: job for job in jobs_for(engine, Settings())}

        assert jobs["notification_reconsider"].run == engine.reconsider_notifications
        assert not hasattr(AssistantEngine, "reconsider_notifications")
    finally:
        await engine.aclose()


async def test_the_reconsideration_job_can_be_disabled_but_never_by_zero(
    tmp_path: Path,
) -> None:
    """ADR-0083 §7's convention, inherited by ADR-0130 §5's new row.

    "Off" and "as fast as possible" cannot be confused by a value — which is the
    one confusion a scheduler cannot afford, because on a completion-scheduled
    loop a zero interval turns this into a hot loop against SQLite.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        disabled = jobs_for(engine, Settings(notification_reconsider_interval=None))

        assert "notification_reconsider" not in [job.name for job in disabled]
    finally:
        await engine.aclose()

    with pytest.raises(ValidationError):
        Settings(notification_reconsider_interval=timedelta(0))


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
            Settings(
                retention_purge_interval=None,
                conversation_sweep_interval=None,
                notification_reconsider_interval=None,
            ),
        )
        assert none_at_all == ()

        with_observation = jobs_for(engine, Settings(observation_interval=timedelta(hours=6)))
        assert [job.name for job in with_observation] == [
            "retention_purge",
            "conversation_sweep",
            "observation",
            "notification_reconsider",
        ]
        assert with_observation[2].run == engine.observe
    finally:
        await engine.aclose()


def _reader_settings(tmp_path: Path, *, interval: timedelta | None) -> Settings:
    """Settings that configure the calendar source, and optionally arm its job.

    The path is set in both cases: ``Settings`` refuses an interval whose source is
    unset (ADR-0093 §7a's incoherent fourth state), and an engine built without the
    path would hold no reader for the job to reach.
    """
    return Settings(
        embedder=EmbedderKind.HASHING,
        calendar_reader_path=tmp_path / "calendar.ics",
        calendar_reader_interval=interval,
    )


async def test_the_calendar_reader_job_is_absent_until_an_operator_arms_it(
    tmp_path: Path,
) -> None:
    """ADR-0093 §7: a reader ships disabled, and §6: enabled is then a real option.

    The two clauses pull in different directions and both are asserted, because
    honouring one alone is a plausible mistake in either direction. §7's default is
    a **consent** decision — "nothing may read a user's personal files because a
    default said so — not that anything technical is missing" — so a fresh
    deployment arms nothing. §6 then says the reason observation ships disabled
    "is specific to observation and does not transfer": §9's gate is ADR-0092,
    which is ratified, so an operator who sets an interval gets a job that runs,
    where arming observation would still buy repeated cost and no new coverage.
    """
    settings = _reader_settings(tmp_path, interval=None)
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        unarmed = jobs_for(engine, settings)
        assert [job.name for job in unarmed] == [
            "retention_purge",
            "conversation_sweep",
            "notification_reconsider",
        ]

        armed_settings = _reader_settings(tmp_path, interval=timedelta(hours=6))
        armed = jobs_for(engine, armed_settings)
        assert [job.name for job in armed] == [
            "retention_purge",
            "conversation_sweep",
            "calendar_reader",
            "notification_reconsider",
        ]
        assert armed[2].interval == timedelta(hours=6)
        # The body is a **public ``Engine`` call**, by identity and not by name: a
        # job that held a reader, a store or a subsystem import would be the shape
        # ADR-0083 §8 forbids and ADR-0093 §6 restates.
        assert armed[2].run == engine.ingest_calendar
    finally:
        await engine.aclose()


async def test_an_unreadable_source_is_logged_by_class_and_never_by_path(
    tmp_path: Path,
) -> None:
    """ADR-0093 §6 and §8's two halves, asserted end to end over the real façade.

    §6: "A failing reader job never takes the process down. It is logged with its
    class and retried at its next due instant" — stronger here than for the jobs
    that clause was written for, because a reader's source is a file the system
    does not own, so unreadability is an ordinary state of the world rather than a
    defect. The source below simply does not exist, which is the commonest of them.

    §8: the error's message is **payload-free**, carrying the reader's identity and
    the failure's class and never the source's location. That is the clause a
    conforming wrapper can satisfy while `raise ReaderError(str(exc)) from exc`
    quietly puts ``/home/alice/Private/therapy.ics`` into an operational log, which
    ADR-0004 §5 forbids outright. Asserted against the log the scheduler actually
    writes rather than against the exception, because the log is where the harm
    would land.
    """
    settings = _reader_settings(tmp_path, interval=_TICK)
    # Granted below, because the subject is a *source* failure: ADR-0097 §5's
    # refusal is a different fact from ADR-0093 §8's, and an ungranted engine would
    # log a `SourceNotGrantedError` while this case asserts on the reader's own
    # class. Granted through the surface rather than through an injected fake seam,
    # which is what ADR-0102 §7 makes possible: `build_engine` opens the store.
    engine = build_engine(settings, data_dir=tmp_path)
    await engine.grant(CALENDAR_READER_NAME, scope=[GrantScope.INGEST])
    twice = asyncio.Event()
    attempts = 0

    async def counting() -> object:
        nonlocal attempts
        attempts += 1
        if attempts >= 2:
            twice.set()
        return await engine.ingest_calendar()

    try:
        with structlog.testing.capture_logs() as captured:
            await _drive(Scheduler([_job("calendar_reader", counting)]), until=twice)
    finally:
        await engine.aclose()

    assert attempts >= 2, "the job was not retried after its source failed"
    failures = [entry for entry in captured if entry["event"] == "hub_scheduler_job_failed"]
    assert failures, _events(captured)
    assert failures[0]["job"] == "calendar_reader"
    assert failures[0]["error_class"] == "ReaderError"
    rendered = repr(captured)
    assert "calendar.ics" not in rendered
    assert str(tmp_path) not in rendered


def _write_one_event_calendar(path: Path) -> None:
    """Put one event an hour from now at ``path`` — a source a granted job can read.

    Duplicated from ``tests/app/test_composition.py`` rather than shared, and
    deliberately: a test of the *scheduler* should not reach into the composition
    root's test module for its fixture, and the two subjects happen to need the
    same three lines of iCalendar rather than sharing a concern.

    **Anchored on the real clock, which is a known dependency rather than an
    oversight (#658).** ``CalendarReader``'s window is clock-relative by definition
    (ADR-0093 §5) and the composition root deliberately injects no clock into it —
    nothing at that layer has a second clock to hand it, and inventing one would be
    the second time source ADR-0093 §7b refuses. So an hour's lead inside the
    seven-day default window (§7a) is a margin and not a guarantee, and only a
    suspension longer than that between writing the file and the tick can breach
    it. The eventual fix is a clock seam in ``build_engine``, which is a design
    change owing its own decision; #658 names this site among those that move with
    it.
    """
    begins = datetime.now(UTC) + timedelta(hours=1)
    ends = begins + timedelta(minutes=30)
    stamp = "%Y%m%dT%H%M%SZ"
    path.write_bytes(
        (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//ai-assistant tests//EN\r\n"
            "BEGIN:VEVENT\r\nUID:e1\r\nDTSTAMP:20260101T000000Z\r\n"
            f"DTSTART:{begins.strftime(stamp)}\r\nDTEND:{ends.strftime(stamp)}\r\n"
            "SUMMARY:Dentist\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        ).encode()
    )


def _armed_calendar_job(engine: Engine, settings: Settings) -> Job:
    """The ``calendar_reader`` job ``jobs_for`` actually builds, for driving.

    Taken from the real table rather than assembled here, so what the loop below
    runs is the **bound ``Engine.ingest_calendar``** a deployment arms and not a
    stand-in
    that happens to share its name (ADR-0083 §8).
    """
    return {job.name: job for job in jobs_for(engine, settings)}["calendar_reader"]


async def test_the_armed_job_ingests_a_granted_source_and_reports_completion(
    tmp_path: Path,
) -> None:
    """Leg 6's exit test with the **scheduler** in the chain, not just the engine.

    ``tests/app/test_composition.py`` already proves that a granted source becomes
    a belief when ``Engine.ingest_calendar`` is called directly. What nothing exercised is
    the leg between: that the job ADR-0083 §7 arms, driven by the real loop on a
    real interval, gets from an ``.ics`` on disk to a belief the user can read.
    That is the whole of what "the assistant knows something true about the user's
    day it was never told" needs a *hub* for, and it is the one step of the chain a
    person exercises without ever calling an engine method.

    The success half is asserted as well as the outcome — ``hub_scheduler_job_completed``
    and **no** ``hub_scheduler_job_failed`` — because a job that raised and was
    absorbed would leave the belief count unchanged and look identical to one that
    never ran (ADR-0022 §4a's shape, at the scheduler).

    **Two ticks are awaited, and the signal is raised only once the body has
    returned** — which is the whole of what makes the second one real. Signalling
    *before* awaiting the job would wake ``_drive`` into cancelling the scheduler
    with the second ingestion still in flight, so the test would assert over one
    completed run while claiming two. Raising it afterwards is safe in the
    direction that matters: ``Scheduler._run_job`` reaches its ``_log.info`` with
    no ``await`` between the body returning and the log, and its first suspension
    point is the ``asyncio.sleep`` after re-arming — so every completed attempt is
    certainly logged before a cancellation can land.

    That earns the second property rather than assuming it: both ingestions really
    run, so a re-read folding into the record it already wrote — rather than
    duplicating it — is something this asserts (ADR-0093 §5's "nothing the store
    holds is destroyed by a re-read", from the other side).
    """
    settings = _reader_settings(tmp_path, interval=_TICK)
    _write_one_event_calendar(tmp_path / "calendar.ics")
    engine = build_engine(settings, data_dir=tmp_path)
    # Through the surface a user uses, never an injected fake seam: ADR-0102 §7
    # opens the store in the composition root, so the grant this job is gated on is
    # a real row in ``grants.db`` (ADR-0097 §1's declared identity as the key).
    await engine.grant(CALENDAR_READER_NAME, scope=[GrantScope.INGEST])
    armed = _armed_calendar_job(engine, settings)
    twice = asyncio.Event()
    attempts = 0

    async def counting() -> object:
        nonlocal attempts
        # Counted and signalled in a ``finally``, so an attempt is only "done" once
        # the job has actually returned or raised — see the docstring.
        try:
            return await armed.run()
        finally:
            attempts += 1
            if attempts >= 2:
                twice.set()

    try:
        with structlog.testing.capture_logs() as captured:
            await _drive(Scheduler([_job("calendar_reader", counting)]), until=twice)
        beliefs = await engine.beliefs()
    finally:
        await engine.aclose()

    assert not [entry for entry in captured if entry["event"] == "hub_scheduler_job_failed"], (
        _events(captured)
    )
    completed = [entry for entry in captured if entry["event"] == "hub_scheduler_job_completed"]
    # Two, not one: both ingestions ran to completion, which is what makes the
    # single belief below evidence of folding rather than of a cancelled re-read.
    assert len(completed) >= 2, _events(captured)
    assert {entry["job"] for entry in completed} == {"calendar_reader"}
    assert len(beliefs) == 1
    assert "Dentist" in beliefs[0].content


async def test_an_ungranted_source_is_refused_every_interval_and_never_by_path(
    tmp_path: Path,
) -> None:
    """ADR-0097 §5's ruled behaviour, and §8's legibility clause **at the log**.

    §5 settles what an armed job over an ungranted source does, in as many words:
    "A deployment that revokes a grant while leaving ``calendar_reader_interval``
    set therefore logs a refusal every interval, and that is the correct behaviour
    rather than a defect to design around: it is configuration and consent
    disagreeing out loud." The operator's fix is to unset the interval — a
    configuration act answering a configuration fact.

    **This is the test that fails if anyone re-implements "the job arms when
    configured *and* granted".** That reading is live in #675's lane-4 bullet,
    which predates ADR-0097 and contradicts it; a scheduler that consulted the
    grant before arming would emit no log line here at all, and §8's marked clause
    — "the refusal is legible to an operator: the log line names the source's
    identity and the use that was refused" — would have nothing to be satisfied by.
    Silence would then be indistinguishable from a healthy deployment reading
    nothing, which is exactly the failure ADR-0022 §4a refuses and §5's choice of
    ``SourceNotGrantedError`` over an empty success exists to prevent.

    **Asserted against the log the scheduler actually writes rather than against
    the exception, because the log is where the harm would land** — the sibling
    case's argument, and it transfers whole. ``tests/orchestration/test_ingestion.py``
    already pins the message on ``SourceNotGrantedError`` itself; nothing pinned
    what reaches an operational log, which is the place ADR-0004 §5 forbids Tier 1
    data outright.

    **The source exists and is readable here**, unlike the sibling case's missing
    file, so the refusal is provably the *grant* and not the source: ADR-0097 §5
    requires that nothing be opened at all, and a test over an unreadable file
    could not tell the two refusals apart.

    **"Every interval" is asserted as two refusals, and the signal is raised only
    once the job has raised.** Both halves are needed. One refusal would pass
    against a regression in which the first tick refuses and every later tick
    returns an empty success — the "reports health while ingesting nothing" state
    §5 chose an exception to prevent. And signalling *before* awaiting the job
    would wake ``_drive`` into cancelling the scheduler mid-tick, so the second
    refusal would never be logged to assert on. Raising it afterwards is sound
    because ``Scheduler._run_job`` reaches ``_log_failure`` with no ``await``
    between the body raising and the log, and its first suspension point is the
    ``asyncio.sleep`` after re-arming.
    """
    settings = _reader_settings(tmp_path, interval=_TICK)
    _write_one_event_calendar(tmp_path / "calendar.ics")
    # Nothing is granted. ADR-0097 §8: no grant is minted from configuration, an
    # existing path included — "an installation that has been reading a source
    # stops reading it until the user grants".
    engine = build_engine(settings, data_dir=tmp_path)
    armed = _armed_calendar_job(engine, settings)
    twice = asyncio.Event()
    attempts = 0

    async def counting() -> object:
        nonlocal attempts
        # Counted and signalled in a ``finally``, so an attempt is only "done" once
        # the job has actually raised — see the docstring.
        try:
            return await armed.run()
        finally:
            attempts += 1
            if attempts >= 2:
                twice.set()

    try:
        with structlog.testing.capture_logs() as captured:
            await _drive(Scheduler([_job("calendar_reader", counting)]), until=twice)
        beliefs = await engine.beliefs()
    finally:
        await engine.aclose()

    # "Every interval", which is the half a one-shot assertion would miss: the
    # refusal is retried at the next due instant and never takes the loop down.
    assert attempts >= 2, "the job was not retried after its grant was refused"
    failures = [entry for entry in captured if entry["event"] == "hub_scheduler_job_failed"]
    # **Two refusals, not one.** Asserting a single one would pass against a
    # regression in which the first tick refuses and every later tick returns an
    # empty success — which is precisely the "reports health while ingesting
    # nothing" state ADR-0022 §4a refuses and §5 chose an exception to prevent.
    assert len(failures) >= 2, _events(captured)
    assert {entry["job"] for entry in failures} == {"calendar_reader"}
    # Never a ``ReaderError``: an operator debugging a missing calendar must not be
    # sent to the filesystem for a fault that lives in the grant store (§5).
    # Asserted over **every** refusal, not just the first: §8's clause binds the
    # log line an operator reads at any interval, not the opening one.
    assert {entry["error_class"] for entry in failures} == {"SourceNotGrantedError"}
    # §8's two halves: the identity and the use that was refused...
    for failure in failures:
        cause = str(failure["cause"])
        assert CALENDAR_READER_NAME in cause
        assert GrantScope.INGEST.value in cause
    # ...and nothing else. A declared identity is safe by construction (ADR-0093
    # §7); a path is the Tier 1 leak the clause exists to prevent.
    rendered = repr(captured)
    assert "calendar.ics" not in rendered
    assert str(tmp_path) not in rendered
    # Nothing was opened, so nothing was proposed and nothing was written (§5).
    assert not beliefs, beliefs


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


def test_an_interval_that_is_not_exactly_a_timedelta_is_refused() -> None:
    """A positivity check alone cannot make ADR-0083 §7's "finite" true.

    ``timedelta`` is subclassable, and a subclass whose ``total_seconds()`` returns
    ``nan`` clears every comparison a positivity guard can make — ``nan <= 0`` is
    ``False``. It then poisons the due instant it is added to, so ``due > now`` and
    ``delay > 0`` are both ``False`` and the loop spins without ever sleeping: the
    SQLite hot loop §7 refuses zero intervals to prevent, arrived at by a route no
    zero-check covers.

    A *native* ``timedelta`` cannot hold a non-finite value, so the exact-type
    requirement is what makes "finite" true — the same argument, in the same words,
    that ``core.config``'s ``_only_a_duration`` already makes with
    ``type(value) is timedelta``.

    The lie is asserted as well as the refusal, so this stays a test about a
    *bypass* rather than about a type annotation.
    """

    class _Lying(timedelta):
        def total_seconds(self) -> float:
            return math.nan

    lying = _Lying(hours=1)
    assert math.isnan(lying.total_seconds())
    assert not lying.total_seconds() <= 0  # what a positivity-only guard would see

    with pytest.raises(TypeError, match="exactly a timedelta"):
        _job("spinner", _nothing, every=lying)


def test_two_jobs_may_not_share_a_name() -> None:
    """A name is the table's **key**, so a duplicate is a job that never runs.

    Due instants are held per name. With two jobs called ``purge``, the first
    re-arms the shared entry before the loop reaches the second, so the second is
    skipped at every tick — forever — while ``hub_ready`` lists it and nothing logs
    its absence. §7 says the loop "runs every due job", and *silently never ran* is
    the single worst failure available to a maintenance job: ADR-0078 §1's exposure
    cap would go unkept by a hub reporting itself healthy.

    Refused at construction rather than survived at runtime, because the loop
    cannot report a job it does not know it is missing.
    """
    with pytest.raises(ValueError, match=r"job names must be unique.*'purge'"):
        Scheduler([_job("purge", _nothing), _job("sweep", _nothing), _job("purge", _nothing)])


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


async def test_consolidation_is_not_armable_while_its_in_chunk_deadline_is_open(
    tmp_path: Path,
) -> None:
    """ADR-0111 §4: the arming path is withheld, not merely defaulted off (#820).

    §4's second clause makes a per-operation deadline "a precondition of being
    chunked at all", and a consolidation chunk's writes reach the ``Embedder``
    through ``MemoryStore.write_atomic`` with no deadline. A disabled default is
    ADR-0083 §7's instrument for a job that *may* be armed; §4's bar is stricter —
    the configuration must not be reachable — so there is no row and no setting.

    Asserted rather than left to prose, because the lane that closes #820 adds both
    back and this is what tells it the pair is the unit: a row without the setting
    arms nothing, and a setting without the row is a config field that lies.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        assert "consolidation" not in {job.name for job in jobs_for(engine, Settings())}
        assert not hasattr(Settings(), "consolidation_interval")
    finally:
        await engine.aclose()


async def test_the_consolidation_engine_operation_runs_against_an_empty_store(
    tmp_path: Path,
) -> None:
    """The composition wiring, exercised rather than assumed.

    ``Engine.consolidate`` refuses when no stage is wired (ADR-0022 §4a's shape),
    so a composition root that failed to build one would raise here rather than
    report an empty success. Called on the façade rather than through ``jobs_for``,
    because no row arms it yet — which is exactly what makes this the case that
    keeps the wiring honest in the meantime. An empty store needs no model call, so
    this stays offline and deterministic while crossing every seam the job uses.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        report = await engine.consolidate()

        assert report.exhausted is True
        assert report.examined == 0
    finally:
        await engine.aclose()


def _producer_settings(tmp_path: Path, *, interval: timedelta | None) -> Settings:
    """Settings that configure the calendar source, and optionally arm the producer.

    The path is set in both cases for ``_reader_settings``' reasons exactly:
    ``Settings`` refuses an armed producer with no source (ADR-0132 §4), and an
    engine built without the path holds no producer stage for the job to reach.
    """
    return Settings(
        embedder=EmbedderKind.HASHING,
        calendar_reader_path=tmp_path / "calendar.ics",
        calendar_upcoming_interval=interval,
    )


async def test_the_upcoming_event_job_is_absent_until_an_operator_arms_it(
    tmp_path: Path,
) -> None:
    """ADR-0132 §4: the interval is ``None`` until an operator sets it.

    ADR-0093 §7's rule for the same source unchanged — "nothing may read a user's
    personal files because a default said so" — so the row is simply absent rather
    than present and skipped, and ``hub_ready`` reports the names that are actually
    armed. The armed half is asserted beside it because honouring one alone is a
    plausible mistake in either direction: a producer that never appears is a
    switch nobody can flip.
    """
    settings = _producer_settings(tmp_path, interval=None)
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        unarmed = jobs_for(engine, settings)
        assert "calendar_upcoming" not in [job.name for job in unarmed]

        armed_settings = _producer_settings(tmp_path, interval=timedelta(minutes=5))
        armed = {job.name: job for job in jobs_for(engine, armed_settings)}
        assert armed["calendar_upcoming"].interval == timedelta(minutes=5)
        # The body is a **public ``Engine`` call**, by identity and not by name: a
        # job that held a reader, a store or a subsystem import would be the shape
        # ADR-0083 §8 forbids and ADR-0132 §1 restates.
        assert armed["calendar_upcoming"].run == engine.notice_upcoming_events
        # And it is *not* on the client-facing surface: no client asks for it and
        # no interface adapter may drive it (ADR-0083 §8).
        assert not hasattr(AssistantEngine, "notice_upcoming_events")
    finally:
        await engine.aclose()


async def test_arming_the_producer_arms_no_ingestion_and_the_reverse(tmp_path: Path) -> None:
    """ADR-0132 §4: the two jobs over one source have two intervals.

    "Arming or retuning one of these two changes ingestion's cadence in no way, and
    arming ingestion arms no producer." The scheduler is where that independence is
    observable, and a lane that reused ``calendar_reader_interval`` for both would
    pass every test about either job on its own.
    """
    engine = build_engine(_producer_settings(tmp_path, interval=None), data_dir=tmp_path)
    try:
        producing = jobs_for(engine, _producer_settings(tmp_path, interval=timedelta(minutes=5)))
        ingesting = jobs_for(engine, _reader_settings(tmp_path, interval=timedelta(hours=6)))

        producing_names = [job.name for job in producing]
        ingesting_names = [job.name for job in ingesting]
        assert "calendar_upcoming" in producing_names
        assert "calendar_reader" not in producing_names
        assert "calendar_reader" in ingesting_names
        assert "calendar_upcoming" not in ingesting_names
    finally:
        await engine.aclose()


async def test_the_producer_job_can_be_disabled_but_never_by_zero(tmp_path: Path) -> None:
    """ADR-0083 §7's convention, inherited by ADR-0132 §4's new row.

    On a completion-scheduled loop a zero interval turns a periodic re-read of the
    user's calendar into a hot loop, and "off" and "as fast as possible" look
    identical in a config file.
    """
    engine = build_engine(_producer_settings(tmp_path, interval=None), data_dir=tmp_path)
    try:
        assert jobs_for(engine, _producer_settings(tmp_path, interval=None)) is not None
        with pytest.raises(ValidationError):
            _producer_settings(tmp_path, interval=timedelta(0))
    finally:
        await engine.aclose()


# --- the second ingestion source (ADR-0140, ADR-0142) ----------------------


def _mail_settings(
    tmp_path: Path,
    *,
    interval: timedelta | None,
    calendar_interval: timedelta | None = None,
) -> Settings:
    """Settings configuring the mail store, and optionally arming either ingestion.

    ``_reader_settings``' shape for the second source. The **path is set in both
    cases** for its reason exactly: ``Settings`` refuses an interval whose
    ``email_source_path`` is unset (ADR-0140 §12), and an engine built without the
    path holds no stage for the job to reach.

    **The calendar is off unless a case asks for it**, and that default is the point
    rather than convenience: ADR-0142 §1 rules that no source's arming is derived
    from, defaulted from or conditioned on another's, so a helper that armed both
    together would make the independence untestable from here.
    """
    return Settings(
        embedder=EmbedderKind.HASHING,
        email_source_path=tmp_path / "mail.mbox",
        email_reader_interval=interval,
        calendar_reader_path=tmp_path / "calendar.ics",
        calendar_reader_interval=calendar_interval,
    )


async def test_both_ingestion_sources_are_armed_under_distinct_names_and_intervals(
    tmp_path: Path,
) -> None:
    """ADR-0142 §9 test 1: the case every single-source test passes while broken.

    #1030's failure mode 1 is a lane that satisfies ADR-0140 §13 by replacing the
    calendar's stage and row with email's — email ingests, the calendar silently
    stops, and every test written against one source at a time still passes. What
    catches it is asserting the *pair*: two rows, distinct names, and each row's
    interval its own source's.

    **The two intervals are deliberately different.** Equal ones would be satisfied
    by an implementation that read one field for both rows, which is precisely the
    defaulting §1's second clause forbids.
    """
    settings = _mail_settings(
        tmp_path, interval=timedelta(minutes=30), calendar_interval=timedelta(hours=6)
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        assert engine._calendar_ingestion is not None
        assert engine._email_ingestion is not None

        armed = {job.name: job for job in jobs_for(engine, settings)}

        assert armed["calendar_reader"].interval == timedelta(hours=6)
        assert armed["email_reader"].interval == timedelta(minutes=30)
    finally:
        await engine.aclose()


async def test_a_configured_mail_store_with_no_interval_arms_nothing_and_disables_nothing(
    tmp_path: Path,
) -> None:
    """ADR-0142 §9 test 2: the legal state §2 reserves, asserted in both halves.

    §2's marked clause: "A source whose path is configured and whose interval is
    unset is a legal, meaningful state per source: its ingestion stage exists and its
    ingestion operation reaches that source's grant gate when called rather than
    refusing as unwired, and no scheduler row is armed for it."

    **Both halves, because a lane that keyed the stage off the interval passes the
    first and fails the second.** No row is armed, *and* ``ingest_email`` still
    succeeds when called directly.

    **The grant is part of the arrangement rather than incidental to it.** Without
    one the operation raises ``SourceNotGrantedError`` (§7) and this test would be
    asserting the wrong refusal — it would pass against an implementation that built
    no stage at all, since ADR-0142 §6's ``ConfigurationError`` and §7's refusal are
    different facts and only one of them is the subject here.
    """
    settings = _mail_settings(tmp_path, interval=None)
    _write_one_mail_message(tmp_path / "mail.mbox")
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        assert "email_reader" not in [job.name for job in jobs_for(engine, settings)]

        await engine.grant(EMAIL_READER_NAME, scope=[GrantScope.INGEST])
        report = await engine.ingest_email()
        assert report.source == EMAIL_READER_NAME
        # Not merely "did not refuse": the read reached the store and proposed from
        # it, so the unarmed stage is a *working* stage with no caller rather than
        # one that returns an empty success (ADR-0093 §8's two outcomes).
        assert report.proposed == 1
    finally:
        await engine.aclose()


async def test_either_ingestion_source_stands_alone(tmp_path: Path) -> None:
    """ADR-0142 §9 test 3: neither source requires the other to be configured.

    Catches "an implementation in which email ingestion requires a configured
    calendar, or the reverse" — the coupling a lane introduces by keying one
    source's wiring off a field that happens to be set in every fixture. Both
    directions are asserted, because a single-direction test is passed by an
    implementation that has the dependency the other way round.

    The refusal asserted is ADR-0142 §6's ``ConfigurationError`` rather than a
    missing row: an operation whose stage was never built is a *wiring* fault, and
    §6 requires it to say so rather than report an empty success.
    """
    mail_only = Settings(
        embedder=EmbedderKind.HASHING,
        email_source_path=tmp_path / "mail.mbox",
        email_reader_interval=timedelta(minutes=30),
    )
    engine = build_engine(mail_only, data_dir=tmp_path)
    try:
        assert "email_reader" in [job.name for job in jobs_for(engine, mail_only)]
        with pytest.raises(ConfigurationError):
            await engine.ingest_calendar()
    finally:
        await engine.aclose()

    calendar_only = _reader_settings(tmp_path, interval=timedelta(hours=6))
    engine = build_engine(calendar_only, data_dir=tmp_path)
    try:
        armed = [job.name for job in jobs_for(engine, calendar_only)]
        assert "calendar_reader" in armed
        assert "email_reader" not in armed
        with pytest.raises(ConfigurationError):
            await engine.ingest_email()
    finally:
        await engine.aclose()


async def test_each_ingestion_row_holds_the_engines_own_bound_method(
    tmp_path: Path,
) -> None:
    """ADR-0142 §9 test 5, scheduler half: the bound method itself, not a stand-in.

    §4's second marked clause: an ingestion source's row holds that operation "as a
    **bound method of the engine** — not a wrapper, a closure, a
    ``functools.partial`` or any other object standing in for it".

    **The shape this exists to catch satisfies ``JobBody`` and passes every
    behavioural test in §9's list.** ``functools.partial(engine.ingest, "email")``
    is callable, takes no arguments and ingests the right source; what it costs is
    §4's whole argument — one seam for every source in the ``OPERATION`` trace, and a
    wiring typo that type-checks and fails at the first tick instead of at ``mypy``.
    So the assertion is on ``__func__`` and ``__self__`` rather than on behaviour:
    the operation is the engine's own, and the engine is *this* one.
    """
    settings = _mail_settings(
        tmp_path, interval=timedelta(minutes=30), calendar_interval=timedelta(hours=6)
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        armed = {job.name: job for job in jobs_for(engine, settings)}

        for name, operation in (
            ("calendar_reader", Engine.ingest_calendar),
            ("email_reader", Engine.ingest_email),
        ):
            run = armed[name].run
            assert getattr(run, "__func__", None) is operation, name
            assert getattr(run, "__self__", None) is engine, name
    finally:
        await engine.aclose()


async def test_the_armed_set_names_both_sources_and_renames_neither(
    tmp_path: Path,
) -> None:
    """ADR-0142 §9 test 9: ``email_reader`` beside ``calendar_reader``, unchanged.

    ``Job.name`` is "Stable identifier for the log and for ``hub_ready``'s job list",
    so it crosses the wire to a client. ADR-0142 §5 renames the *method* and
    deliberately leaves the row alone — "a lane that 'tidied' it to match the method
    name would be making a wire-visible change for no reason" — and this is what
    would catch that tidying.

    The names come from :meth:`Scheduler.job_names` rather than from the table,
    because that is the value ``hub_ready`` actually reports.
    """
    settings = _mail_settings(
        tmp_path, interval=timedelta(minutes=30), calendar_interval=timedelta(hours=6)
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        names = Scheduler(jobs_for(engine, settings)).job_names

        assert "calendar_reader" in names
        assert "email_reader" in names
        assert "ingest_calendar" not in names, "the row name is not the method name"
    finally:
        await engine.aclose()


async def test_one_sources_failing_ingestion_leaves_the_others_job_running(
    tmp_path: Path,
) -> None:
    """ADR-0142 §9 test 8: the coupling a multiplexing stage would have introduced.

    §7's second marked clause: "One ingestion source's job failing, refusing for want
    of a grant, or being unarmed neither disarms, delays beyond ADR-0083 §7's serial
    duty cycle, nor alters the outcome of any other source's ingestion job."

    **The failure is real rather than simulated**: the mail store simply does not
    exist, which is the commonest way a reader's source fails and raises
    ``ReaderError`` every tick. The calendar's own row is driven beside it on the
    same loop, and what is asserted is that it keeps completing — the property a
    single stage looping over two readers would break, because one reader's
    ``ReaderError`` would abort the loop and the sibling would not be read at all
    that tick.

    The email body is the engine's own bound method; the calendar's is wrapped only
    to count its runs, which is what lets the case assert that the sibling kept
    going rather than merely that the loop stayed up. Ticking rather than the real
    intervals, for the same reason every driven case in this module does.
    """
    _write_one_event_calendar(tmp_path / "calendar.ics")
    # The mail store is deliberately absent, so every email tick raises.
    settings = _mail_settings(tmp_path, interval=_TICK, calendar_interval=_TICK)
    engine = build_engine(settings, data_dir=tmp_path)
    calendar_runs = 0
    twice = asyncio.Event()

    async def counting_calendar() -> object:
        nonlocal calendar_runs
        calendar_runs += 1
        if calendar_runs >= 2:
            twice.set()
        return await engine.ingest_calendar()

    try:
        await engine.grant(CALENDAR_READER_NAME, scope=[GrantScope.FACET, GrantScope.INGEST])
        await engine.grant(EMAIL_READER_NAME, scope=[GrantScope.FACET, GrantScope.INGEST])
        with structlog.testing.capture_logs() as captured:
            await _drive(
                Scheduler(
                    [
                        _job("calendar_reader", counting_calendar),
                        _job("email_reader", engine.ingest_email),
                    ]
                ),
                until=twice,
            )
    finally:
        await engine.aclose()

    assert calendar_runs >= 2, "the calendar's job stopped when email's failed"
    failures = [entry for entry in captured if entry["event"] == "hub_scheduler_job_failed"]
    assert failures, _events(captured)
    assert {entry["job"] for entry in failures} == {"email_reader"}
    assert failures[0]["error_class"] == "ReaderError"


def _write_one_mail_message(path: Path) -> None:
    """Put one message delivered an hour ago at ``path`` — a store a granted job reads.

    Duplicated from ``tests/app/test_composition.py`` rather than shared, and
    deliberately, for :func:`_write_one_event_calendar`'s reason exactly: a test of
    the *scheduler* should not reach into the composition root's test module for its
    fixture, and the two subjects happen to need the same few lines of mbox rather
    than sharing a concern.

    Anchored on the real clock, which is a known dependency rather than an oversight
    (#658): ``EmailReader``'s window is clock-relative by definition (ADR-0140 §3)
    and the composition root deliberately injects no clock into it. An hour back
    inside the seven-day default window (ADR-0140 §12) is a margin and not a
    guarantee.
    """
    delivered = datetime.now(UTC) - timedelta(hours=1)
    path.write_bytes(
        (
            "From nobody@invalid Thu Jan  1 00:00:00 1970\n"
            "From: Alice <alice@example.com>\n"
            "Subject: Standup moved to ten\n"
            f"Date: {format_datetime(delivered)}\n"
            f"X-Assistant-Delivered-At: {delivered:%Y-%m-%dT%H:%M:%SZ}\n"
            "\n"
        ).encode()
    )
