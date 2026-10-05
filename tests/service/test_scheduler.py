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
from ai_assistant.core.config import EmbedderKind, Settings, load_settings
from ai_assistant.core.protocols import AssistantEngine
from ai_assistant.core.types import GrantScope
from ai_assistant.orchestration.consolidation import ConsolidationReport
from ai_assistant.orchestration.engine import ENGINE_SHUTTING_DOWN, Engine
from ai_assistant.readers import CALENDAR_READER_NAME
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
    """§7's table, built over a real engine: three jobs armed by default.

    A real ``Engine`` rather than a stand-in, because the claim being made is about
    *which methods the jobs are bound to* — and a fake with the right attribute
    names would satisfy that assertion while proving nothing about the façade the
    hub actually holds.

    **Three enabled by default**, and no observation job among them (ADR-0285 §3).
    The reconsideration job's own default is minutes for ADR-0130 §5's reason:
    "with no producers it rules nothing, and a held record whose window has passed
    is the one thing this ADR cannot leave to a later act".
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


async def test_no_observation_job_is_scheduled_even_where_the_old_variable_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0285 §3 and §11:3: "The scheduler arms no observation job."

    Through production composition: the hub's own ``load_settings``, ``build_engine``
    and ``jobs_for``, over an environment that still carries the variable a
    pre-change deployment set to arm it — which is the cutover §5 warns about,
    where a setting naming no field is ignored without an error. Every interval is
    armed beside it, so the table this reads is the widest a deployment can build,
    and the check is over every row's name *and* every row's bound method: a job
    renamed but still bound to an observation body would pass a name check alone.
    """
    monkeypatch.setenv("ASSISTANT_OBSERVATION_INTERVAL", "PT6H")
    monkeypatch.setenv("ASSISTANT_EMBEDDER", "hashing")
    monkeypatch.setenv("ASSISTANT_CONSOLIDATION_INTERVAL", "PT6H")
    settings = load_settings()
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        jobs = jobs_for(engine, settings)

        assert "consolidation" in {job.name for job in jobs}, "the table is the armed one"
        assert not any("observ" in job.name for job in jobs)
        assert not any("observ" in getattr(job.run, "__name__", "") for job in jobs)
        assert not hasattr(engine, "observe_due")
        assert not hasattr(engine, "observe")
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
    that line a lie.
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

        without_purge = jobs_for(engine, Settings(retention_purge_interval=None))
        assert [job.name for job in without_purge] == [
            "conversation_sweep",
            "notification_reconsider",
        ]
    finally:
        await engine.aclose()


async def test_no_ingestion_job_is_scheduled_even_where_the_old_variables_are_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0294 §1 and §5: no job reads a source to propose what it read into memory.

    Through production composition, on the shape ADR-0285 §3's observation case
    uses: the hub's own ``load_settings``, ``build_engine`` and ``jobs_for``, over
    an environment that still carries the two variables a pre-change deployment set
    to arm ingestion. ``Settings`` ignores a variable that names no field, so the
    hub starts without an error and arms nothing from them — which is the cutover
    ADR-0294 §5 names. Both sources are configured and every other interval is
    armed, so the table read here is the widest a deployment can build; the check
    is over every row's name *and* every row's bound method.
    """
    _write_one_event_calendar(tmp_path / "calendar.ics")
    _write_one_mail_message(tmp_path / "mail.mbox")
    monkeypatch.setenv("ASSISTANT_CALENDAR_READER_INTERVAL", "PT6H")
    monkeypatch.setenv("ASSISTANT_EMAIL_READER_INTERVAL", "PT6H")
    monkeypatch.setenv("ASSISTANT_EMBEDDER", "hashing")
    monkeypatch.setenv("ASSISTANT_CALENDAR_READER_PATH", str(tmp_path / "calendar.ics"))
    monkeypatch.setenv("ASSISTANT_EMAIL_SOURCE_PATH", str(tmp_path / "mail.mbox"))
    monkeypatch.setenv("ASSISTANT_CALENDAR_UPCOMING_INTERVAL", "PT5M")
    monkeypatch.setenv("ASSISTANT_CONSOLIDATION_INTERVAL", "PT6H")
    settings = load_settings()
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        jobs = jobs_for(engine, settings)

        assert "calendar_upcoming" in {job.name for job in jobs}, "the table is the armed one"
        assert not any("reader" in job.name for job in jobs)
        assert not any("ingest" in getattr(job.run, "__name__", "") for job in jobs)
        assert not hasattr(engine, "ingest_calendar")
        assert not hasattr(engine, "ingest_email")
        assert not hasattr(settings, "calendar_reader_interval")
        assert not hasattr(settings, "email_reader_interval")
    finally:
        await engine.aclose()


async def test_an_unreadable_source_is_logged_by_class_and_never_by_path(
    tmp_path: Path,
) -> None:
    """ADR-0093 §6 and §8's two halves, asserted end to end over the real façade.

    Driven through the upcoming-event producer, the one scheduled job that reads a
    source (ADR-0132 §9 gives it the same disposition). §6: "A failing reader job
    never takes the process down. It is logged with its
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
    settings = _producer_settings(tmp_path, interval=_TICK)
    # Granted below, because the subject is a *source* failure: ADR-0097 §5's
    # refusal is a different fact from ADR-0093 §8's, and an ungranted engine would
    # log a `SourceNotGrantedError` while this case asserts on the reader's own
    # class. Granted through the surface rather than through an injected fake seam,
    # which is what ADR-0102 §7 makes possible: `build_engine` opens the store.
    engine = build_engine(settings, data_dir=tmp_path)
    await engine.grant(CALENDAR_READER_NAME, scope=[GrantScope.NOTIFY])
    twice = asyncio.Event()
    attempts = 0

    async def counting() -> object:
        nonlocal attempts
        attempts += 1
        if attempts >= 2:
            twice.set()
        return await engine.notice_upcoming_events()

    try:
        with structlog.testing.capture_logs() as captured:
            await _drive(Scheduler([_job("calendar_upcoming", counting)]), until=twice)
    finally:
        await engine.aclose()

    assert attempts >= 2, "the job was not retried after its source failed"
    failures = [entry for entry in captured if entry["event"] == "hub_scheduler_job_failed"]
    assert failures, _events(captured)
    assert failures[0]["job"] == "calendar_upcoming"
    assert failures[0]["error_class"] == "ReaderError"
    rendered = repr(captured)
    assert "calendar.ics" not in rendered
    assert str(tmp_path) not in rendered


def _write_one_event_calendar(path: Path, *, starts_in: timedelta = timedelta(hours=1)) -> None:
    """Put one event ``starts_in`` from now at ``path`` — a source a granted job can read.

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
    begins = datetime.now(UTC) + starts_in
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


def _armed_producer_job(engine: Engine, settings: Settings) -> Job:
    """The ``calendar_upcoming`` job ``jobs_for`` actually builds, for driving.

    Taken from the real table rather than assembled here, so what the loop below
    runs is the **bound ``Engine.notice_upcoming_events``** a deployment arms and
    not a stand-in that happens to share its name (ADR-0083 §8).
    """
    return {job.name: job for job in jobs_for(engine, settings)}["calendar_upcoming"]


async def test_the_armed_producer_notices_a_granted_source_and_reports_completion(
    tmp_path: Path,
) -> None:
    """The producer with the **scheduler** in the chain, not just the engine.

    What this exercises is the leg between a configured interval and an offered
    candidate: that the job ADR-0083 §7 arms, driven by the real loop on a real
    interval, gets from an ``.ics`` on disk to a candidate offered through the
    notification seam. It is the one step of the chain a person exercises without
    ever calling an engine method.

    The success half is asserted as well as the outcome — ``hub_scheduler_job_completed``
    and **no** ``hub_scheduler_job_failed`` — because a job that raised and was
    absorbed would offer nothing and look identical to one that never ran
    (ADR-0022 §4a's shape, at the scheduler).

    **Two ticks are awaited, and the signal is raised only once the body has
    returned** — which is the whole of what makes the second one real. Signalling
    *before* awaiting the job would wake ``_drive`` into cancelling the scheduler
    with the second run still in flight, so the test would assert over one completed
    run while claiming two. Raising it afterwards is safe in the direction that
    matters: ``Scheduler._run_job`` reaches its ``_log.info`` with no ``await``
    between the body returning and the log, and its first suspension point is the
    ``asyncio.sleep`` after re-arming — so every completed attempt is certainly
    logged before a cancellation can land.
    """
    settings = _producer_settings(tmp_path, interval=_TICK)
    _write_one_event_calendar(tmp_path / "calendar.ics", starts_in=timedelta(minutes=10))
    engine = build_engine(settings, data_dir=tmp_path)
    # Through the surface a user uses, never an injected fake seam: ADR-0102 §7
    # opens the store in the composition root, so the grant this job is gated on is
    # a real row in ``grants.db`` (ADR-0097 §1's declared identity as the key).
    await engine.grant(CALENDAR_READER_NAME, scope=[GrantScope.NOTIFY])
    armed = _armed_producer_job(engine, settings)
    twice = asyncio.Event()
    offered: list[object] = []
    attempts = 0

    async def counting() -> object:
        nonlocal attempts
        # Counted and signalled in a ``finally``, so an attempt is only "done" once
        # the job has actually returned or raised — see the docstring.
        try:
            count = await armed.run()
            offered.append(count)
            return count
        finally:
            attempts += 1
            if attempts >= 2:
                twice.set()

    try:
        with structlog.testing.capture_logs() as captured:
            await _drive(Scheduler([_job("calendar_upcoming", counting)]), until=twice)
    finally:
        await engine.aclose()

    assert not [entry for entry in captured if entry["event"] == "hub_scheduler_job_failed"], (
        _events(captured)
    )
    completed = [entry for entry in captured if entry["event"] == "hub_scheduler_job_completed"]
    assert len(completed) >= 2, _events(captured)
    assert {entry["job"] for entry in completed} == {"calendar_upcoming"}
    # The occurrence inside the lead window was offered on the first run.
    assert offered[0] == 1


async def test_an_ungranted_source_is_refused_every_interval_and_never_by_path(
    tmp_path: Path,
) -> None:
    """ADR-0097 §5's ruled behaviour, and §8's legibility clause **at the log**.

    §5 settles what an armed job over an ungranted source does, in as many words:
    "A deployment that revokes a grant while leaving ``calendar_reader_interval``
    set therefore logs a refusal every interval, and that is the correct behaviour
    rather than a defect to design around: it is configuration and consent
    disagreeing out loud." That interval is retired with ingestion (ADR-0294 §5);
    the rule binds the upcoming-event producer's armed row on the same terms
    (ADR-0133 §5), which is what is driven here. The operator's fix is to unset the
    interval — a configuration act answering a configuration fact.

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
    case's argument, and it transfers whole: what reaches an operational log is the
    place ADR-0004 §5 forbids Tier 1 data outright.

    **The source exists and is readable here**, unlike the sibling case's missing
    file, so the refusal is provably the *grant* and not the source: ADR-0097 §5
    requires that nothing be opened at all, and a test over an unreadable file
    could not tell the two refusals apart.

    **"Every interval" is asserted as two refusals, and the signal is raised only
    once the job has raised.** Both halves are needed. One refusal would pass
    against a regression in which the first tick refuses and every later tick
    returns an empty success — the "reports health while reading nothing" state
    §5 chose an exception to prevent. And signalling *before* awaiting the job
    would wake ``_drive`` into cancelling the scheduler mid-tick, so the second
    refusal would never be logged to assert on. Raising it afterwards is sound
    because ``Scheduler._run_job`` reaches ``_log_failure`` with no ``await``
    between the body raising and the log, and its first suspension point is the
    ``asyncio.sleep`` after re-arming.
    """
    settings = _producer_settings(tmp_path, interval=_TICK)
    _write_one_event_calendar(tmp_path / "calendar.ics", starts_in=timedelta(minutes=10))
    # Nothing is granted. ADR-0097 §8: no grant is minted from configuration, an
    # existing path included — "an installation that has been reading a source
    # stops reading it until the user grants".
    engine = build_engine(settings, data_dir=tmp_path)
    armed = _armed_producer_job(engine, settings)
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
            await _drive(Scheduler([_job("calendar_upcoming", counting)]), until=twice)
        held = await engine.notifications()
    finally:
        await engine.aclose()

    # "Every interval", which is the half a one-shot assertion would miss: the
    # refusal is retried at the next due instant and never takes the loop down.
    assert attempts >= 2, "the job was not retried after its grant was refused"
    failures = [entry for entry in captured if entry["event"] == "hub_scheduler_job_failed"]
    # **Two refusals, not one.** Asserting a single one would pass against a
    # regression in which the first tick refuses and every later tick returns an
    # empty success — which is precisely the "reports health while reading
    # nothing" state ADR-0022 §4a refuses and §5 chose an exception to prevent.
    assert len(failures) >= 2, _events(captured)
    assert {entry["job"] for entry in failures} == {"calendar_upcoming"}
    # Never a ``ReaderError``: an operator debugging a missing calendar must not be
    # sent to the filesystem for a fault that lives in the grant store (§5).
    # Asserted over **every** refusal, not just the first: §8's clause binds the
    # log line an operator reads at any interval, not the opening one.
    assert {entry["error_class"] for entry in failures} == {"SourceNotGrantedError"}
    # §8's two halves: the identity and the use that was refused...
    for failure in failures:
        cause = str(failure["cause"])
        assert CALENDAR_READER_NAME in cause
        assert GrantScope.NOTIFY.value in cause
    # ...and nothing else. A declared identity is safe by construction (ADR-0093
    # §7); a path is the Tier 1 leak the clause exists to prevent.
    rendered = repr(captured)
    assert "calendar.ics" not in rendered
    assert str(tmp_path) not in rendered
    # Nothing was opened, so nothing was offered and nothing was held (§5).
    assert not held, held


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
    render — a result naming beliefs is Tier 1 content — so it renders none of them. A
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


async def test_the_consolidation_job_is_absent_until_an_operator_arms_it(
    tmp_path: Path,
) -> None:
    """ADR-0111 §11 and §4, from both sides — and the pair is the unit (#820, #1487).

    §4's second clause made a per-operation deadline "a precondition of being
    chunked at all", and a chunk's writes reached the ``Embedder`` through
    ``MemoryStore.write_atomic`` with none — so until ADR-0118 the configuration was
    withheld rather than defaulted off, which is a stricter bar than ADR-0083 §7's
    disabled default. That deadline landed, and §11 leaves the arming itself to "an
    implementation lane's act against this text once ratified".

    Both directions are asserted because honouring one alone is a plausible mistake
    in either: a row without the setting arms nothing, and a setting without the row
    is a config field that lies — which is the state #1487 found live, where the
    stage was wired, the operation callable, and no path in a running hub reached
    it.

    **The row is last, and that is asserted rather than incidental.** Every job is
    due at the first tick and this is the one bounded by a budget rather than by its
    backlog, so a position earlier in the table would put up to one
    ``scheduler_run_budget`` between a boot and the retention purge that follows it.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        assert Settings().consolidation_interval is None
        unarmed = jobs_for(engine, Settings())
        assert "consolidation" not in {job.name for job in unarmed}

        armed = jobs_for(engine, Settings(consolidation_interval=timedelta(hours=6)))
        assert [job.name for job in armed] == [
            "retention_purge",
            "conversation_sweep",
            "notification_reconsider",
            "consolidation",
        ]
        assert armed[-1].interval == timedelta(hours=6)
        # By identity, not by name: ADR-0083 §8's "every job is a bound public
        # engine method", and ADR-0111 §1's cursor stays below the façade because
        # the body takes no argument and this row neither reads it nor passes it.
        assert armed[-1].run == engine.consolidate
    finally:
        await engine.aclose()


async def test_the_consolidation_job_can_be_disabled_but_never_by_zero(
    tmp_path: Path,
) -> None:
    """ADR-0083 §7's convention, inherited unchanged by ADR-0111 §11's new row.

    "Off" and "as fast as possible" cannot be confused by a value. The hazard is
    the loop's for every row — a completion-scheduled job with a zero interval is
    due again the instant it finishes — and it is worse for this one than for the
    purge that clause was written against, because a run of this job spends a model
    call per chunk rather than only a transaction.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        disabled = jobs_for(engine, Settings(consolidation_interval=None))

        assert "consolidation" not in {job.name for job in disabled}
    finally:
        await engine.aclose()

    with pytest.raises(ValidationError):
        Settings(consolidation_interval=timedelta(0))


async def test_the_armed_consolidation_row_runs_on_the_real_loop(
    tmp_path: Path,
) -> None:
    """#1487's gap closed end to end: the loop reaches ``Engine.consolidate``.

    The composition root has always built the stage and the façade has always
    exposed the operation — ``Engine.consolidate`` refuses when no stage is wired
    (ADR-0022 §4a's shape), so a root that failed to build one raises here rather
    than reporting an empty success. What nothing exercised is the leg between: that
    a hub whose operator set an interval actually runs it. That is the whole of
    #1487, whose finding was that in a deployed hub this producer could not run at
    all, so the property it is measured on held vacuously.

    Driven through the row ``jobs_for`` builds rather than through a hand-made
    :class:`Job`, so the thing under test is the table's own body. Two ticks are
    awaited, and the signal is raised only once the body has returned, for
    ``test_the_armed_producer_notices_a_granted_source_and_reports_completion``'s reason
    exactly.

    An empty store needs no model call — ``walk_records`` answers with no position
    and the run is exhausted before a chunk exists — so this stays offline and
    deterministic while crossing every seam the job uses.
    """
    settings = Settings(embedder=EmbedderKind.HASHING, consolidation_interval=_TICK)
    engine = build_engine(settings, data_dir=tmp_path)
    armed = next(job for job in jobs_for(engine, settings) if job.name == "consolidation")
    twice = asyncio.Event()
    reports: list[ConsolidationReport] = []
    attempts = 0

    async def counting() -> object:
        nonlocal attempts
        try:
            report = await armed.run()
        finally:
            attempts += 1
            if attempts >= 2:
                twice.set()
        assert isinstance(report, ConsolidationReport)
        reports.append(report)
        return report

    try:
        with structlog.testing.capture_logs() as captured:
            await _drive(Scheduler([_job("consolidation", counting)]), until=twice)
    finally:
        await engine.aclose()

    assert not [entry for entry in captured if entry["event"] == "hub_scheduler_job_failed"], (
        _events(captured)
    )
    completed = [entry for entry in captured if entry["event"] == "hub_scheduler_job_completed"]
    assert len(completed) >= 2, _events(captured)
    assert {entry["job"] for entry in completed} == {"consolidation"}
    # The run's own disposition, so a job that was absorbed as a no-op cannot pass
    # for one that walked: exhausted, over nothing.
    assert reports[0].exhausted is True
    assert reports[0].examined == 0


def _producer_settings(tmp_path: Path, *, interval: timedelta | None) -> Settings:
    """Settings that configure the calendar source, and optionally arm the producer.

    The path is set in both cases: ``Settings`` refuses an armed producer with no
    source (ADR-0132 §4), and an engine built without the path holds no producer
    stage for the job to reach.
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
