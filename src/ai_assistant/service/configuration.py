"""ADR-0119 §9's startup stamp: one ``CONFIGURATION`` trace per hub startup.

§9 is the fourth and last of §8's emitting seams, and the only one that is not a
crossing of anything — it records a *state* rather than an event, at the one
instant the state is known to be settled: "At every hub startup, after the stores
are open and before the API accepts a request, ``service`` emits one
``CONFIGURATION`` trace recording the effective value of each setting on a
declared list of measurement-relevant settings."

**Every startup, not only on change** (§9). "A change is derivable by diffing
consecutive configuration traces, and the converse is not true: an 'on change'
stamp needs prior state to compare against, which after a crash it does not
have." It also makes the stream self-describing about downtime — a gap between a
shutdown and the next configuration trace is a hub that was not running, which a
measure must not read as a period of no activity.

**The list is an allowlist and it fails closed** (§9). A setting reaches a trace
only by being named in :data:`ALLOWLIST_KEYS` below, so no ``Settings`` object is
ever recorded whole and no field added later is recorded by default. ``Settings``
holds no Tier 0 value, but it does hold ``data_dir`` — a path that on a normal
machine contains the user's account name — and provider and model identifiers. A
denylist would admit the next field somebody adds; this admits nothing until
somebody names it. :func:`_allowlisted` is the only place the list is read, and
every entry is an explicit attribute access rather than a lookup by name, so the
set is a list of lines a reviewer can count.

**What "measurement-relevant" is taken to mean here**, since §9 states the
property and leaves the roster to this lane. A setting is on the list when it
either bounds the trace stream itself — how long a trace survives to be measured
— or shapes the memory accumulation leg 8's measures are computed over: whether
each job that grows the user model is armed and how often it runs, how much one
of its passes may read or propose, and the deadline every retrieval's embedding
call is bound by. Two more are on it because §9 puts them there: the effective
``search`` limit of each cardinality control (below).

**What is deliberately off it.** Paths and model identifiers, which §9's third
clause excludes by name — ``data_dir``, ``embedder``, the model routes and their
credentials. The transport's four figures, the four permission-gate thresholds,
the deferral queue's tuning, the calendar reader's *content* bounds, the locale,
the log level and the drain budget: each shapes the system, none shapes a
quantity the leg-8 measures are computed from, and §9's "when in doubt, leave it
off" decides the ones that are arguable. A later change that needs one adds it,
which is the same rule §9 states for a cardinality control added later.

**A stamp that cannot be written is subordinate** (§5). Startup never fails,
retries, or changes because a trace could not be recorded; the loss is a Tier 2
log record naming the kind, the seam and the failure's class. §9 names the cost
rather than papering over it: "A window whose configuration traces are missing
cannot date its intervention from them, which is the entry criterion unmet — so
the log record is the operator's cue, and the condition self-heals at the next
restart."

**Nothing here reads a datum.** Every string this module can put in a trace is a
literal constant below or a ``StrEnum`` member from ``core/types.py``; every
value is an ``int``, a ``float`` or a ``bool`` (§2). No path, no model name, no
exception message.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.types import (
    EvaluationTrace,
    TraceKind,
    TraceOutcome,
    fault_class_of,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import timedelta

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.config import Settings
    from ai_assistant.core.protocols import TraceSink

_log = structlog.get_logger(__name__)

#: The event name an emission failure is logged under (ADR-0119 §5). Duplicated
#: from the two pipeline emitters and from ``ai_assistant.evaluation``'s durable
#: store rather than imported, for the reason they duplicate it from each other:
#: no subsystem may name another's concrete module, and `service` may not name
#: ``ai_assistant.evaluation`` at all (``lint-imports``). An operator greps one
#: string and finds every lost trace, whichever side lost it.
TRACE_NOT_RECORDED: Final = "trace_not_recorded"

#: What the log record carries in place of a seam that is not a representable
#: label, so an unvalidated string never reaches a Tier 2 log (ADR-0004 §5).
#: Duplicated for :data:`TRACE_NOT_RECORDED`'s reason.
UNREADABLE_TRACE_FIELD: Final = "unreadable"

#: The seam pattern, duplicated from ``core/types.py``'s private ``_TRACE_LABEL``
#: for the one use :func:`_dropped` has for it, exactly as the other two emitters
#: duplicate it. A test builds a trace with :data:`SEAM_STARTUP` as its seam, so
#: the duplicate cannot drift into accepting what the type refuses.
_SEAM_LABEL: Final = re.compile(r"[a-z][a-z0-9_]{0,63}")

#: Where the stamp happens, as a literal constant in the emitting module (§2).
#: The hub's own startup, between ADR-0083 §3's step 3 and its step 4.
SEAM_STARTUP: Final = "hub_startup"

# --- the allowlist: job cadence -----------------------------------------------
# The four intervals ADR-0083 §7 and ADR-0093 §7a give the scheduler, each as a
# pair: whether the job is armed at all, and — when it is — how often it runs.
#
# **Two keys rather than one, and the boolean is the load-bearing half.** All four
# are nullable, and `None` means *disabled*, never *zero* (ADR-0083 §7). §3's
# observation rule makes an absent metric key mean "not observed", so encoding
# "off" as an absent key would make a disabled job indistinguishable from a hub
# whose build never had the setting. The value **was** observed; what it was
# observed to be is "off", and a boolean is how a number-or-boolean record says
# so (§9's third clause).
#
# **`observation_interval` is the closest live analogue of #829's arming**, and
# the reason this pair shape is worth the keys: it ships disabled, an operator
# turns it on, and the before/after is exactly what #829 requires be datable.

#: Whether the retention purge is armed (ADR-0083 §7). It expires memory records,
#: reclaims purgeable deferred questions, and sweeps the trace store itself
#: (ADR-0119 §10) — so it bounds both the corpus and the stream measured over it.
RETENTION_PURGE_ARMED: Final = "retention_purge_interval_armed"

#: How often it runs, present only when armed.
RETENTION_PURGE_SECONDS: Final = "retention_purge_interval_seconds"

#: Whether the conversation sweep is armed (ADR-0083 §7). It finishes pending
#: deletions and reclaims what episode retention has emptied, so it decides how
#: fast the retrieval corpus shrinks.
CONVERSATION_SWEEP_ARMED: Final = "conversation_sweep_interval_armed"

#: How often it runs, present only when armed.
CONVERSATION_SWEEP_SECONDS: Final = "conversation_sweep_interval_seconds"

#: Whether belief distillation is armed (ADR-0083 §7, ADR-0077). This is the job
#: that *grows* the user model, and it ships disabled — so the moment it is armed
#: is an intervention no measure of accuracy may straddle unknowingly.
OBSERVATION_ARMED: Final = "observation_interval_armed"

#: How often it runs, present only when armed.
OBSERVATION_SECONDS: Final = "observation_interval_seconds"

#: Whether scheduled calendar ingestion is armed (ADR-0093 §7a). It is the
#: producer of the coverage readings whose absences close validity windows
#: (ADR-0110, ADR-0117), which is the population #824's trigger is stated over.
CALENDAR_READER_ARMED: Final = "calendar_reader_interval_armed"

#: How often it runs, present only when armed.
CALENDAR_READER_SECONDS: Final = "calendar_reader_interval_seconds"

# --- the allowlist: what one scheduled run and one observation pass may do ----

#: The per-run deadline a chunked scheduled walk is bound by (ADR-0111 §4). It is
#: what decides an ``INCOMPLETE`` outcome, so a measure counting halted runs is
#: reading a rate this figure sets.
SCHEDULER_RUN_BUDGET_SECONDS: Final = "scheduler_run_budget_seconds"

#: How many records one chunk of a scheduled walk examines (ADR-0111 §4). §9
#: names this one by name as an intervention: "a chunk size or a ``fetch_k``
#: moving mid-window is as much an intervention as an arming".
SCHEDULER_CHUNK_SIZE: Final = "scheduler_chunk_size"

#: How many of a conversation's turns one observation pass reads (ADR-0077 §1).
#: It bounds the evidence behind every belief the pass proposes.
OBSERVATION_BATCH_SIZE: Final = "observation_batch_size"

#: The most beliefs one observation pass may propose; excess is discarded
#: (ADR-0077 §2). It caps the write stream a correction rate is computed over.
OBSERVATION_MAX_PROPOSALS: Final = "observation_max_proposals"

# --- the allowlist: the trace stream's own horizon ----------------------------

#: Whether traces are deleted at all (ADR-0119 §10). ``None`` means *keep
#: forever*, which is not "off" — hence ``finite`` rather than ``armed``: the two
#: nullable retention horizons express an unbounded lifetime, where the four job
#: intervals express a job that never runs, and one word for both would lose the
#: difference.
TRACE_RETENTION_FINITE: Final = "trace_retention_finite"

#: The horizon in seconds, present only when finite. A measurement window longer
#: than this loses its own early rows, silently, which is the one configuration
#: fact a measure over the stream cannot discover from the stream.
TRACE_RETENTION_SECONDS: Final = "trace_retention_seconds"

#: Whether a captured episode is ever deleted (ADR-0074 §7).
EPISODE_RETENTION_FINITE: Final = "episode_retention_finite"

#: How long one survives, present only when finite. Episodes are what observation
#: reads and what a conversation-scoped retrieval returns, so the horizon bounds
#: the corpus every accuracy measure is computed over.
EPISODE_RETENTION_SECONDS: Final = "episode_retention_seconds"

# --- the allowlist: the deadline every retrieval's embedding is bound by ------

#: The per-call embedding deadline (ADR-0118 §4). A retrieval whose query
#: embedding times out reaches no candidate set at all, so this figure sets the
#: rate of ``FAULT`` retrieval traces carrying none of §8's counts.
EMBEDDING_TIMEOUT_SECONDS: Final = "embedding_timeout_seconds"

# --- the allowlist: the cardinality controls §9 puts on it --------------------
# §9 requires "for **every** cardinality control that can drive a traced read
# past §3's ``records`` cap — not a named subset of them — the **effective**
# ``search`` limit that control produces at the seam, which need not equal the
# control's own value". Two hold the property at this date and neither is a
# ``Settings`` field, so both figures are handed over by the composition root.
#
# **These are diagnostics and they exclude nothing** (§9). A limit above §3's cap
# of 256 says a window *could* truncate; whether one did is the individual
# trace's own truncation declaration, and "a complete trace from a deployment
# configured above the cap counts like any other".

#: The largest ``limit`` a turn's retrieval reaches ``MemoryStore.search`` with.
RETRIEVAL_SEARCH_LIMIT: Final = "retrieval_search_limit"

#: The ``limit`` the ingestor's conflict probe reaches ``MemoryStore.search``
#: with — the ceiling **plus two** (ADR-0079 §1). §9: "A ``conflict_limit`` of 255
#: sits under the cap while the probe it drives asks for 257, so a diagnostic
#: keyed to the control would say 'this deployment cannot truncate' of one that
#: can."
CONFLICT_SEARCH_LIMIT: Final = "conflict_search_limit"

#: Every key the allowlist can produce, for the test that pins the list against
#: this module rather than against a reviewer's memory. A key that is emitted and
#: not here, or here and unreachable, is a list that has drifted from its own
#: declaration — which is the failure an allowlist exists to make impossible.
ALLOWLIST_KEYS: Final[frozenset[str]] = frozenset(
    {
        RETENTION_PURGE_ARMED,
        RETENTION_PURGE_SECONDS,
        CONVERSATION_SWEEP_ARMED,
        CONVERSATION_SWEEP_SECONDS,
        OBSERVATION_ARMED,
        OBSERVATION_SECONDS,
        CALENDAR_READER_ARMED,
        CALENDAR_READER_SECONDS,
        SCHEDULER_RUN_BUDGET_SECONDS,
        SCHEDULER_CHUNK_SIZE,
        OBSERVATION_BATCH_SIZE,
        OBSERVATION_MAX_PROPOSALS,
        TRACE_RETENTION_FINITE,
        TRACE_RETENTION_SECONDS,
        EPISODE_RETENTION_FINITE,
        EPISODE_RETENTION_SECONDS,
        EMBEDDING_TIMEOUT_SECONDS,
        RETRIEVAL_SEARCH_LIMIT,
        CONFLICT_SEARCH_LIMIT,
    }
)


def _utcnow() -> datetime:
    """The default clock: the wall clock, in UTC.

    A module-level function rather than a lambda so the seam has a name in a
    traceback, matching every other default clock in the tree.

    Returns:
        The current instant, timezone-aware.
    """
    return datetime.now(UTC)


class ConfigurationStamp:
    """Emits ADR-0119 §9's one ``CONFIGURATION`` trace per hub startup.

    One instance per hub process, constructed from what the composition root
    produced and driven once by the startup sequence.

    **The sink is required and has no default** (§7). "A composition that omits it
    does not type-check", because an optional sink defaults to unwired, an unwired
    emitter produces no traces, and no traces is indistinguishable from no events
    — §5's lie arriving through composition instead of through I/O.

    **The seam holds an append and not a walk** (§7): a
    :class:`~ai_assistant.core.protocols.TraceSink` and never a ``TraceStore``, so
    nothing here can read a trace back. `service` may not name
    ``ai_assistant.evaluation`` at all, so the annotation and the ``lint-imports``
    contract agree rather than merely coexisting.
    """

    def __init__(
        self,
        *,
        sink: TraceSink,
        retrieval_search_limit: int,
        conflict_search_limit: int,
        now: Clock = _utcnow,
    ) -> None:
        """Hold the sink, the clock and the two figures only the root knows.

        Args:
            sink: The trace store's **append** seam.
            retrieval_search_limit: The effective ``search`` limit the learning
                loop's ``retrieval_limit`` produces (ADR-0119 §9). Supplied by the
                composition root, which is the only layer that knows it —
                ``Settings`` holds no such field, so "a ``Settings`` dump would
                show neither".
            conflict_search_limit: The effective ``search`` limit the ingestor's
                ``conflict_limit`` produces, which is the ceiling plus two.
            now: The clock the instant is stamped from. §3 puts the stamp on the
                emitter rather than on the store, because a store stamping on
                append "would measure the write rather than the event". Guarded by
                :func:`~ai_assistant.core.clock.checked_clock` (ADR-0026 §7) like
                every other injected clock in this tree; a reading it refuses
                costs the trace and never the startup (§5).
        """
        self._sink = sink
        self._retrieval_search_limit = retrieval_search_limit
        self._conflict_search_limit = conflict_search_limit
        self._now = checked_clock(now, owner="ConfigurationStamp")

    async def record(self, settings: Settings) -> None:
        """Stamp this hub's effective configuration. **Never raises** (§5).

        Guarded end to end and not only around the sink, because §2's and §3's
        constraints are enforced at *construction*: a metric key that is not a
        label, a value that is not finite. Each would be a bug in this module, and
        §5 admits no exception for first-party bugs — "no retrieval, write, turn,
        scheduled run or startup fails, retries, or changes its result because a
        trace could not be written".

        **A cancellation is never classified** (§3, ADR-0060 §1). ``except
        Exception`` does not catch ``CancelledError``, which is a
        ``BaseException``, so a stop signal delivered mid-startup leaves here
        untouched and no trace records it.

        **No correlation reference** (§4). §4 binds the reference to "every trace
        emitted while serving one ``AssistantEngine`` operation"; a startup stamp
        is outside every operation, and ``None`` is the honest answer there. The
        ambient identifier is therefore not read at all rather than read and found
        empty.

        **No duration.** ``elapsed`` records how long a crossing took, and this
        crossing is a state being read rather than work being done, so nothing was
        observed and the field stays ``None`` (§3's observation rule, applied to
        the one field that is not a metric).

        Args:
            settings: The effective settings this hub started with. Only the
                allowlisted fields are read; the object is never recorded whole.
        """
        try:
            occurred_at = self._now()
            trace = EvaluationTrace(
                kind=TraceKind.CONFIGURATION,
                seam=SEAM_STARTUP,
                occurred_at=occurred_at,
                outcome=TraceOutcome.OK,
                metrics=self._allowlisted(settings),
            )
        # Broad by design: §5 lets no clock fault and no emitter bug reach startup.
        except Exception as error:
            _dropped(error)
            return
        try:
            await self._sink.emit(trace)
        # Broad by design: §7 says a conforming sink cannot raise here, and §5 says
        # what to do if one does anyway.
        except Exception as error:
            _dropped(error)

    def _allowlisted(self, settings: Settings) -> Mapping[str, int | float | bool]:
        """The declared list, read field by field (ADR-0119 §9).

        **Every entry is an explicit attribute access.** A loop over field names
        would compose each read from a string and make the allowlist a table one
        indirection away from the reader; the point of an allowlist is that it can
        be counted, so it is written as lines.

        Args:
            settings: The settings to read the allowlisted fields from.

        Returns:
            The metrics mapping, ready for the trace. Durations are seconds.
        """
        metrics: dict[str, int | float | bool] = {
            SCHEDULER_RUN_BUDGET_SECONDS: settings.scheduler_run_budget.total_seconds(),
            SCHEDULER_CHUNK_SIZE: settings.scheduler_chunk_size,
            OBSERVATION_BATCH_SIZE: settings.observation_batch_size,
            OBSERVATION_MAX_PROPOSALS: settings.observation_max_proposals,
            EMBEDDING_TIMEOUT_SECONDS: settings.embedding_timeout_seconds,
            RETRIEVAL_SEARCH_LIMIT: self._retrieval_search_limit,
            CONFLICT_SEARCH_LIMIT: self._conflict_search_limit,
        }
        _pair(
            metrics,
            RETENTION_PURGE_ARMED,
            RETENTION_PURGE_SECONDS,
            settings.retention_purge_interval,
        )
        _pair(
            metrics,
            CONVERSATION_SWEEP_ARMED,
            CONVERSATION_SWEEP_SECONDS,
            settings.conversation_sweep_interval,
        )
        _pair(metrics, OBSERVATION_ARMED, OBSERVATION_SECONDS, settings.observation_interval)
        _pair(
            metrics,
            CALENDAR_READER_ARMED,
            CALENDAR_READER_SECONDS,
            settings.calendar_reader_interval,
        )
        _pair(metrics, TRACE_RETENTION_FINITE, TRACE_RETENTION_SECONDS, settings.trace_retention)
        _pair(
            metrics, EPISODE_RETENTION_FINITE, EPISODE_RETENTION_SECONDS, settings.episode_retention
        )
        return metrics


def _pair(
    metrics: dict[str, int | float | bool],
    present: str,
    seconds: str,
    value: timedelta | None,
) -> None:
    """Record a nullable duration as a boolean and, when set, a number.

    The one shape every nullable setting on the list takes, in one place so the
    six cannot drift in how they say "not set".

    Args:
        metrics: The mapping under construction; mutated in place.
        present: The key carrying whether the duration is set.
        seconds: The key carrying its length, written only when it is.
        value: The setting's effective value.
    """
    metrics[present] = value is not None
    if value is not None:
        metrics[seconds] = value.total_seconds()


def _dropped(error: Exception) -> None:
    """Log a configuration trace that could not be recorded (ADR-0119 §5).

    "Emission failure is never silent", because a measure over a stream with
    dropped rows reports a smaller numerator and does not know it. §9 states this
    seam's particular cost: a window whose configuration traces are missing cannot
    date its intervention from them, so this record is the operator's cue and the
    condition self-heals at the next restart.

    The three keys are Tier 2 by construction: the kind is an enum member, the
    seam is checked against the same pattern the type enforces, and the error's
    **class** goes through §3's total conversion rather than being read raw —
    ADR-0004 §5 is unconditional that logs are Tier 2 only. The message never
    appears.

    Args:
        error: Why the trace was not recorded.
    """
    _log.warning(
        TRACE_NOT_RECORDED,
        kind=str(TraceKind.CONFIGURATION),
        seam=SEAM_STARTUP if _SEAM_LABEL.fullmatch(SEAM_STARTUP) else UNREADABLE_TRACE_FIELD,
        error_class=fault_class_of(error),
    )


__all__ = [
    "ALLOWLIST_KEYS",
    "CALENDAR_READER_ARMED",
    "CALENDAR_READER_SECONDS",
    "CONFLICT_SEARCH_LIMIT",
    "CONVERSATION_SWEEP_ARMED",
    "CONVERSATION_SWEEP_SECONDS",
    "EMBEDDING_TIMEOUT_SECONDS",
    "EPISODE_RETENTION_FINITE",
    "EPISODE_RETENTION_SECONDS",
    "OBSERVATION_ARMED",
    "OBSERVATION_BATCH_SIZE",
    "OBSERVATION_MAX_PROPOSALS",
    "OBSERVATION_SECONDS",
    "RETENTION_PURGE_ARMED",
    "RETENTION_PURGE_SECONDS",
    "RETRIEVAL_SEARCH_LIMIT",
    "SCHEDULER_CHUNK_SIZE",
    "SCHEDULER_RUN_BUDGET_SECONDS",
    "SEAM_STARTUP",
    "TRACE_NOT_RECORDED",
    "TRACE_RETENTION_FINITE",
    "TRACE_RETENTION_SECONDS",
    "UNREADABLE_TRACE_FIELD",
    "ConfigurationStamp",
]
