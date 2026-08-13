"""ADR-0119 §9's startup stamp: what it records, and what it refuses to.

Three properties carry this module, and they are not the same property said three
ways.

**The allowlist is a list.** §9 makes it "an allowlist: a setting reaches a
``CONFIGURATION`` trace only by being named on it, so no ``Settings`` object is
ever recorded whole and no field added later is recorded by default". The tests
below assert both halves — every emitted key is declared, and the declared set is
exactly what two opposite deployments between them produce — because a denylist
and an allowlist look identical on any single deployment and differ only on the
field somebody adds next.

**Nothing in the trace is Tier 0 or Tier 1.** §2 makes that checkable rather than
a matter of intent: every value is a number or a boolean, and no string in the
record is derived from a datum. A ``Settings`` object holds a data directory whose
path carries the user's account name on a normal machine, so the strongest form of
that test is to point one at a distinctive path and assert the whole serialised
trace does not contain it.

**The instrument is subordinate** (§5). A sink that raises, a clock that will not
read: each costs the trace and never the startup, and each leaves a log record,
because "a missing trace is indistinguishable from a non-event".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import structlog

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import TraceStoreError
from ai_assistant.core.types import EvaluationTrace, TraceKind, TraceOutcome
from ai_assistant.service.configuration import (
    ALLOWLIST_KEYS,
    CALENDAR_READER_ARMED,
    CALENDAR_READER_SECONDS,
    CONFLICT_SEARCH_LIMIT,
    CONVERSATION_SWEEP_ARMED,
    CONVERSATION_SWEEP_SECONDS,
    EMBEDDING_TIMEOUT_SECONDS,
    EPISODE_RETENTION_FINITE,
    EPISODE_RETENTION_SECONDS,
    NOTIFICATION_QUEUE_LIMIT,
    NOTIFICATION_RECONSIDER_ARMED,
    NOTIFICATION_RECONSIDER_SECONDS,
    NOTIFICATION_RETENTION_FINITE,
    NOTIFICATION_RETENTION_SECONDS,
    OBSERVATION_ARMED,
    OBSERVATION_BATCH_SIZE,
    OBSERVATION_MAX_PROPOSALS,
    OBSERVATION_SECONDS,
    RETENTION_PURGE_ARMED,
    RETENTION_PURGE_SECONDS,
    RETRIEVAL_SEARCH_LIMIT,
    SCHEDULER_CHUNK_SIZE,
    SCHEDULER_RUN_BUDGET_SECONDS,
    SEAM_STARTUP,
    TRACE_NOT_RECORDED,
    TRACE_RETENTION_FINITE,
    TRACE_RETENTION_SECONDS,
    ConfigurationStamp,
)
from ai_assistant.testing import FakeTraceSink

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

#: The figures a test hands the stamp in place of the composition root's. Chosen
#: distinct from every default on the list so a key crossed with another fails.
_RETRIEVAL_LIMIT = 7
_CONFLICT_LIMIT = 102

_INSTANT = datetime(2026, 8, 9, 10, 30, tzinfo=UTC)


def _clock() -> datetime:
    return _INSTANT


def _stamp(sink: Any, *, now: Any = _clock) -> ConfigurationStamp:
    """A stamp over ``sink``, with the two cardinality figures fixed."""
    return ConfigurationStamp(
        sink=sink,
        retrieval_search_limit=_RETRIEVAL_LIMIT,
        conflict_search_limit=_CONFLICT_LIMIT,
        now=now,
    )


async def _recorded(settings: Settings) -> EvaluationTrace:
    """Drive one stamp over ``settings`` and return the single trace it wrote."""
    sink = FakeTraceSink()
    await _stamp(sink).record(settings)
    assert len(sink.recorded) == 1
    return sink.recorded[0]


def _events(captured: Sequence[Mapping[str, Any]]) -> list[str]:
    return [entry["event"] for entry in captured]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A default deployment, pointed at a private directory."""
    return Settings(data_dir=tmp_path / "hub-data")


# --- The envelope (§3, §4, §9) -----------------------------------------------


async def test_one_configuration_trace_is_stamped_per_startup(settings: Settings) -> None:
    """§9's first clause, and §5's one-crossing rule read at this seam.

    "``service`` emits **one** ``CONFIGURATION`` trace" — the kind, the seam and
    the outcome are the axes a measure filters the stream on (§3), so all three
    are pinned rather than assumed from the metrics being right.
    """
    trace = await _recorded(settings)

    assert trace.kind is TraceKind.CONFIGURATION
    assert trace.seam == SEAM_STARTUP
    assert trace.outcome is TraceOutcome.OK
    assert trace.occurred_at == _INSTANT


async def test_the_stamp_carries_no_duration_no_fault_and_no_references(
    settings: Settings,
) -> None:
    """A state read, not a crossing — and outside every engine operation.

    ``elapsed`` is *not observed* here rather than zero: §3's observation rule
    applies to the one non-metric field that can be absent, and a zero duration
    would assert a measurement nobody made. ``refs`` is empty because §4 binds the
    correlation reference to "every trace emitted while serving one
    ``AssistantEngine`` operation", and a startup stamp is serving none — the
    honest answer outside an operation is no reference at all. ``records`` is
    empty because a configuration is about no record.
    """
    trace = await _recorded(settings)

    assert trace.elapsed is None
    assert trace.fault_class is None
    assert dict(trace.refs) == {}
    assert dict(trace.records) == {}


# --- The allowlist (§9's second clause) --------------------------------------


async def test_every_recorded_key_is_on_the_declared_allowlist(settings: Settings) -> None:
    """ "A setting reaches a ``CONFIGURATION`` trace only by being named on it."

    The subset direction: nothing the emitter produces escapes the declaration.
    """
    trace = await _recorded(settings)

    assert set(trace.metrics) <= ALLOWLIST_KEYS


async def test_the_declared_allowlist_is_exactly_what_two_deployments_produce(
    tmp_path: Path,
) -> None:
    """The other direction: no key is declared that nothing can emit.

    Two opposite deployments are needed because eight of the entries are pairs
    whose numeric half appears only when the duration is set — so an armed hub and
    a disarmed one each produce a strict subset, and only their union is the list.
    A declared-but-unreachable key would otherwise sit here forever, describing a
    record no operator will ever meet.
    """
    armed = Settings(
        data_dir=tmp_path / "armed",
        calendar_reader_path=tmp_path / "calendar.ics",
        calendar_reader_interval=timedelta(minutes=15),
        observation_interval=timedelta(hours=6),
    )
    disarmed = Settings(
        data_dir=tmp_path / "disarmed",
        retention_purge_interval=None,
        conversation_sweep_interval=None,
        observation_interval=None,
        episode_retention=None,
        trace_retention=None,
        notification_retention=None,
        notification_reconsider_interval=None,
    )

    keys = set((await _recorded(armed)).metrics) | set((await _recorded(disarmed)).metrics)

    assert keys == ALLOWLIST_KEYS


async def test_a_default_deployment_records_its_effective_figures(settings: Settings) -> None:
    """The allowlist's numeric half, against the shipped defaults.

    Pinned as one mapping rather than key by key, because the property under test
    is the *record an operator reads* — a figure landing under a neighbouring key
    is exactly the failure §9 describes when it insists on the effective limit,
    and a per-key assertion set would pass while the two were swapped.
    """
    trace = await _recorded(settings)

    assert dict(trace.metrics) == {
        RETENTION_PURGE_ARMED: True,
        RETENTION_PURGE_SECONDS: timedelta(hours=1).total_seconds(),
        CONVERSATION_SWEEP_ARMED: True,
        CONVERSATION_SWEEP_SECONDS: timedelta(hours=1).total_seconds(),
        OBSERVATION_ARMED: False,
        CALENDAR_READER_ARMED: False,
        SCHEDULER_RUN_BUDGET_SECONDS: timedelta(minutes=5).total_seconds(),
        SCHEDULER_CHUNK_SIZE: 50,
        OBSERVATION_BATCH_SIZE: 20,
        OBSERVATION_MAX_PROPOSALS: 5,
        TRACE_RETENTION_FINITE: True,
        TRACE_RETENTION_SECONDS: timedelta(days=365).total_seconds(),
        EPISODE_RETENTION_FINITE: True,
        EPISODE_RETENTION_SECONDS: timedelta(days=30).total_seconds(),
        EMBEDDING_TIMEOUT_SECONDS: 30.0,
        RETRIEVAL_SEARCH_LIMIT: _RETRIEVAL_LIMIT,
        CONFLICT_SEARCH_LIMIT: _CONFLICT_LIMIT,
        NOTIFICATION_QUEUE_LIMIT: 100,
        NOTIFICATION_RETENTION_FINITE: True,
        NOTIFICATION_RETENTION_SECONDS: timedelta(days=7).total_seconds(),
        NOTIFICATION_RECONSIDER_ARMED: True,
        NOTIFICATION_RECONSIDER_SECONDS: timedelta(minutes=5).total_seconds(),
    }


async def test_a_disabled_job_is_recorded_as_off_and_not_as_absent(tmp_path: Path) -> None:
    """ "Off" is a value that was observed, and §3 makes absence mean otherwise.

    §3: "An absent key means *not observed* and never zero". A disabled interval
    encoded as a missing key would therefore claim the emitter never looked — and
    a measure could not tell a hub with observation switched off from one built
    before the setting existed. The boolean says which.
    """
    disarmed = Settings(data_dir=tmp_path / "hub-data", retention_purge_interval=None)

    metrics = dict((await _recorded(disarmed)).metrics)

    assert metrics[RETENTION_PURGE_ARMED] is False
    assert RETENTION_PURGE_SECONDS not in metrics


async def test_an_unbounded_horizon_is_recorded_as_not_finite(tmp_path: Path) -> None:
    """``None`` on a retention horizon means *keep forever*, which is not "off".

    The two nullable horizons take a ``finite`` boolean where the four job
    intervals take an ``armed`` one, and the distinction is real: a job that never
    runs and a trace that is never deleted are opposite facts, and one word for
    both would leave a measure guessing which it had.
    """
    forever = Settings(data_dir=tmp_path / "hub-data", trace_retention=None)

    metrics = dict((await _recorded(forever)).metrics)

    assert metrics[TRACE_RETENTION_FINITE] is False
    assert TRACE_RETENTION_SECONDS not in metrics


async def test_an_armed_calendar_reader_records_its_cadence(tmp_path: Path) -> None:
    """The pair's other state, on the one interval a path has to accompany.

    ``Settings`` refuses an interval whose source path is unset (ADR-0093 §7a), so
    this is also the case that proves the armed half is reachable at all.
    """
    armed = Settings(
        data_dir=tmp_path / "hub-data",
        calendar_reader_path=tmp_path / "calendar.ics",
        calendar_reader_interval=timedelta(minutes=15),
    )

    metrics = dict((await _recorded(armed)).metrics)

    assert metrics[CALENDAR_READER_ARMED] is True
    assert metrics[CALENDAR_READER_SECONDS] == timedelta(minutes=15).total_seconds()


async def test_an_armed_observation_job_dates_the_arming(tmp_path: Path) -> None:
    """#829's requirement, in the shape this seam gives it.

    ADR-0119 §9 is #829 requirement 2's carrier — "the arming moment is stamped
    somewhere telemetry can see" — and the live analogue of the consolidation
    arming #829 anticipates is the observation job, which ships disabled. A
    restart after arming therefore writes a trace that differs from the previous
    one in exactly the two keys that moved, which is what makes the before/after
    datable by diffing consecutive configuration traces.
    """
    before = dict((await _recorded(Settings(data_dir=tmp_path / "hub-data"))).metrics)
    after = dict(
        (
            await _recorded(
                Settings(data_dir=tmp_path / "hub-data", observation_interval=timedelta(hours=6))
            )
        ).metrics
    )

    assert before[OBSERVATION_ARMED] is False
    assert OBSERVATION_SECONDS not in before
    assert after[OBSERVATION_ARMED] is True
    assert after[OBSERVATION_SECONDS] == timedelta(hours=6).total_seconds()


async def test_the_two_notification_nullables_take_the_word_their_null_means(
    tmp_path: Path,
) -> None:
    """ADR-0141 §10's two ``_pair`` entries, on the off-branch that names them.

    The three notification figures are on the list because ADR-0141 §8's partition
    needs them, and two of the three are nullable in **opposite** senses. ``None``
    on ``notification_retention`` is the user's "keep them" — an unbounded
    lifetime, so ``finite``, like the two horizons. ``None`` on
    ``notification_reconsider_interval`` disables the job — so ``armed``, like the
    four intervals. Both states are pinned here rather than only the default one,
    because the default deployment has both set and would let either word pass.
    """
    off = Settings(
        data_dir=tmp_path / "hub-data",
        notification_retention=None,
        notification_reconsider_interval=None,
    )

    metrics = dict((await _recorded(off)).metrics)

    assert metrics[NOTIFICATION_RETENTION_FINITE] is False
    assert NOTIFICATION_RETENTION_SECONDS not in metrics
    assert metrics[NOTIFICATION_RECONSIDER_ARMED] is False
    assert NOTIFICATION_RECONSIDER_SECONDS not in metrics


async def test_a_moved_notification_cap_moves_the_recorded_mapping(tmp_path: Path) -> None:
    """ADR-0141 §8's partition is a thing this entry creates, not one it inherits.

    §8 partitions a measurement window "at every ``CONFIGURATION`` trace whose
    metric mapping differs from its predecessor's", and §10 records that before
    this entry "two startups differing only in the cap emit identical
    ``CONFIGURATION`` metric mappings, no boundary is created". This is that
    sentence made false: the cap alone now moves the mapping, so the boundary
    exists for a measure to find.
    """
    before = dict((await _recorded(Settings(data_dir=tmp_path / "hub-data"))).metrics)
    after = dict(
        (
            await _recorded(Settings(data_dir=tmp_path / "hub-data", notification_queue_limit=5))
        ).metrics
    )

    assert before[NOTIFICATION_QUEUE_LIMIT] == 100
    assert after[NOTIFICATION_QUEUE_LIMIT] == 5
    assert before != after


async def test_the_two_cardinality_figures_come_from_the_caller(settings: Settings) -> None:
    """§9's fourth clause: the effective limit, and not a control's own value.

    Neither figure is a ``Settings`` field, so neither can be read here — "a
    ``Settings`` dump would show neither". What the stamp records is what it was
    handed, which is what the composition root produced.
    """
    metrics = dict((await _recorded(settings)).metrics)

    assert metrics[RETRIEVAL_SEARCH_LIMIT] == _RETRIEVAL_LIMIT
    assert metrics[CONFLICT_SEARCH_LIMIT] == _CONFLICT_LIMIT


# --- The tier discipline (§2) ------------------------------------------------


async def test_every_recorded_value_is_a_number_or_a_boolean(tmp_path: Path) -> None:
    """§2's fifth clause, over both branches of every pair.

    "Every non-reference observation a trace carries is a number or a boolean.
    There is no free-text field, no serialised payload and no open-value-type
    mapping anywhere in the family." The type enforces it; this asserts the
    emitter never needs it enforced, which is the difference between a rule that
    holds and one that is being caught.
    """
    armed = Settings(
        data_dir=tmp_path / "armed",
        calendar_reader_path=tmp_path / "calendar.ics",
        calendar_reader_interval=timedelta(minutes=15),
    )

    for value in (await _recorded(armed)).metrics.values():
        assert isinstance(value, int | float | bool)


async def test_the_data_directory_never_reaches_the_trace(tmp_path: Path) -> None:
    """§9's third clause, tested at the field it was written for.

    "``Settings`` … does hold ``data_dir``, a path that on a normal machine
    contains the user's account name." Asserting over the *serialised* trace
    rather than over the metrics mapping is deliberate: it is the only form of the
    test that would also fail if a path reached the seam label, the fault class or
    a reference — the three places a string can legally live.
    """
    marked = tmp_path / "beatrix-mccarthy-private"
    settings = Settings(data_dir=marked)

    trace = await _recorded(settings)

    assert marked.name not in trace.model_dump_json()


def test_the_seam_label_is_one_the_type_accepts() -> None:
    """The duplicated label pattern cannot drift into accepting what the type won't.

    ``_SEAM_LABEL`` is copied from ``core/types.py``'s private original for the one
    use the log record has for it, exactly as the other two emitters copy it. A
    seam this module considered readable and the type refused would lose every
    trace at construction while the log said nothing was wrong.
    """
    trace = EvaluationTrace(
        kind=TraceKind.CONFIGURATION,
        seam=SEAM_STARTUP,
        occurred_at=_INSTANT,
        outcome=TraceOutcome.OK,
    )

    assert trace.seam == SEAM_STARTUP


# --- Subordination (§5) ------------------------------------------------------


class _RaisingSink:
    """A sink that breaches its own contract by letting a store fault escape.

    §7 promises "no trace-store failure escapes"; §5 says what happens if one does
    anyway, and that clause is only worth anything if something upholds it. A
    conforming fake cannot produce this case, which is why the double is here
    rather than :class:`~ai_assistant.testing.FakeTraceSink` with a scripted
    failure — that one swallows, correctly, and would test nothing.
    """

    async def emit(self, trace: EvaluationTrace) -> None:
        """Raise instead of appending.

        Args:
            trace: Ignored.

        Raises:
            TraceStoreError: Always.
        """
        msg = "the trace database is locked"
        raise TraceStoreError(msg)


async def test_a_sink_that_raises_costs_the_trace_and_not_the_startup(
    settings: Settings,
) -> None:
    """§5's first two clauses at this seam, together.

    "No … startup fails, retries, or changes its result because a trace could not
    be written", and "emission failure is never silent". Both, because either one
    alone is a failure mode: a silent swallow makes a measure under-count without
    knowing, and a propagating fault takes down a hub for its instrument.
    """
    with structlog.testing.capture_logs() as captured:
        await _stamp(_RaisingSink()).record(settings)

    assert TRACE_NOT_RECORDED in _events(captured)
    dropped = next(entry for entry in captured if entry["event"] == TRACE_NOT_RECORDED)
    assert dropped["kind"] == str(TraceKind.CONFIGURATION)
    assert dropped["seam"] == SEAM_STARTUP
    assert dropped["error_class"] == "TraceStoreError"


async def test_a_clock_that_will_not_read_costs_the_trace_and_not_the_startup(
    settings: Settings,
) -> None:
    """ADR-0026 §7's guard, subordinated under §5 rather than raised.

    A naive reading is refused by ``checked_clock`` wherever a clock is injected;
    at this seam the refusal must not reach the caller, because a hub that would
    not start because its wall clock lost a timezone is the instrument failing the
    work it observes.
    """
    sink = FakeTraceSink()
    naive = datetime(2026, 8, 9, 10, 30)  # noqa: DTZ001 — the refused reading is the subject

    with structlog.testing.capture_logs() as captured:
        await _stamp(sink, now=lambda: naive).record(settings)

    assert sink.recorded == ()
    assert TRACE_NOT_RECORDED in _events(captured)


async def test_the_log_record_never_carries_an_exception_message(settings: Settings) -> None:
    """ADR-0004 §5 is unconditional, so §2's bound holds on the log side too.

    A trace's ``fault_class`` is the class name and never the message; the log
    record that stands in for a lost trace is a Tier 2 record under the same rule,
    and a message there could quote whatever the store was holding.
    """

    class _Talkative:
        async def emit(self, trace: EvaluationTrace) -> None:
            msg = "row 42 said beatrix-mccarthy prefers oat milk"
            raise TraceStoreError(msg)

    with structlog.testing.capture_logs() as captured:
        await _stamp(_Talkative()).record(settings)

    assert "beatrix-mccarthy" not in repr(captured)
