"""Builders for the trace shapes ADR-0120's populations are defined over.

Shared by the measure suites. Every builder produces what the *merged emitters*
produce — all six decision counts together or none, ``records`` under the
dispositions ``memory/ingest.py`` assigns, a correlation reference on everything
inside an operation — so a test that wants a shape the emitters cannot produce
has to ask for it explicitly, which is the point.

Not named ``conftest.py``: these are constructors a test imports, not fixtures
pytest injects, and importing them by name keeps each suite's dependencies
readable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ai_assistant.core.types import (
    EvaluationTrace,
    NotificationDispositionKind,
    RecordIdSet,
    TraceKind,
    TraceOutcome,
    TraceRecordSet,
    TraceRef,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

#: The window every suite measures over, and the settling period it uses.
START = datetime(2026, 7, 1, tzinfo=UTC)
END = datetime(2026, 8, 1, tzinfo=UTC)
SETTLING = timedelta(hours=24)

#: A default duration, short enough that a write stamped a second later reports
#: having begun after the read reports having finished.
QUICK = timedelta(milliseconds=10)

_DECISIONS = (
    "decisions_accept",
    "decisions_reject",
    "decisions_reinforce",
    "decisions_supersede",
    "decisions_ask_user",
    "decisions_store_temporary",
)


def at(*, days: int = 0, hours: int = 0, seconds: int = 0) -> datetime:
    """An instant that far into the window."""
    return START + timedelta(days=days, hours=hours, seconds=seconds)


def decisions(  # noqa: PLR0913 — one keyword per field the emitter fills
    *,
    accept: int = 0,
    reject: int = 0,
    reinforce: int = 0,
    supersede: int = 0,
    ask_user: int = 0,
    store_temporary: int = 0,
) -> dict[str, int]:
    """All six decision counts, zeros included — the shape a completed crossing has."""
    return dict(
        zip(
            _DECISIONS,
            (accept, reject, reinforce, supersede, ask_user, store_temporary),
            strict=True,
        )
    )


def operation(
    seam: str,
    *,
    when: datetime,
    correlation: str | None = "c1",
    elapsed: timedelta | None = QUICK,
    outcome: TraceOutcome = TraceOutcome.OK,
) -> EvaluationTrace:
    """One ``OPERATION`` trace, as ``Engine._tracked`` emits it."""
    return EvaluationTrace(
        kind=TraceKind.OPERATION,
        seam=seam,
        occurred_at=when,
        elapsed=elapsed,
        outcome=outcome,
        fault_class="RuntimeError"
        if outcome in (TraceOutcome.FAULT, TraceOutcome.REFUSED)
        else None,
        refs={} if correlation is None else {TraceRef.CORRELATION: correlation},
    )


def write(  # noqa: PLR0913 — one keyword per field the emitter fills
    *,
    when: datetime,
    correlation: str | None = "c1",
    metrics: Mapping[str, int | float | bool] | None = None,
    written: tuple[str, ...] = (),
    reinforced: tuple[str, ...] = (),
    superseded: tuple[str, ...] = (),
    retired: tuple[str, ...] = (),
    superseded_total: int | None = None,
    elapsed: timedelta | None = QUICK,
    outcome: TraceOutcome = TraceOutcome.OK,
    seam: str = "memory_ingest_reading",
) -> EvaluationTrace:
    """One ``MEMORY_WRITE`` trace, with whichever id sets the crossing observed."""
    records = {}
    for key, ids in (
        (TraceRecordSet.WRITTEN, written),
        (TraceRecordSet.REINFORCED, reinforced),
        (TraceRecordSet.RETIRED, retired),
    ):
        if ids:
            records[key] = RecordIdSet(ids=ids, total=len(ids))
    if superseded or superseded_total is not None:
        records[TraceRecordSet.SUPERSEDED] = RecordIdSet(
            ids=superseded,
            total=len(superseded) if superseded_total is None else superseded_total,
        )
    return EvaluationTrace(
        kind=TraceKind.MEMORY_WRITE,
        seam=seam,
        occurred_at=when,
        elapsed=elapsed,
        outcome=outcome,
        fault_class="RuntimeError"
        if outcome in (TraceOutcome.FAULT, TraceOutcome.REFUSED)
        else None,
        refs={} if correlation is None else {TraceRef.CORRELATION: correlation},
        records=records,
        metrics=decisions() if metrics is None else metrics,
    )


def retrieval(  # noqa: PLR0913 — one keyword per field the emitter fills
    *,
    when: datetime,
    returned: tuple[str, ...] | None = (),
    returned_total: int | None = None,
    correlation: str | None = "c1",
    counts: Mapping[str, int | float | bool] | None = None,
    elapsed: timedelta | None = QUICK,
    outcome: TraceOutcome = TraceOutcome.OK,
) -> EvaluationTrace:
    """One ``RETRIEVAL`` trace, as ``SqliteMemoryStore`` emits it."""
    records = {}
    if returned is not None:
        records[TraceRecordSet.RETURNED] = RecordIdSet(
            ids=returned,
            total=len(returned) if returned_total is None else returned_total,
        )
    return EvaluationTrace(
        kind=TraceKind.RETRIEVAL,
        seam="memory_search",
        occurred_at=when,
        elapsed=elapsed,
        outcome=outcome,
        fault_class="RuntimeError"
        if outcome in (TraceOutcome.FAULT, TraceOutcome.REFUSED)
        else None,
        refs={} if correlation is None else {TraceRef.CORRELATION: correlation},
        records=records,
        metrics={} if counts is None else counts,
    )


def read_counts(  # noqa: PLR0913 — one keyword per field the emitter fills
    *,
    limit: int = 10,
    fetch_k: int = 40,
    candidates: int = 10,
    returned: int = 10,
    excluded_kind: int = 0,
    excluded_retention: int = 0,
    excluded_window: int = 0,
    excluded_band: int = 0,
) -> dict[str, int]:
    """The eight counts §7 reads, defaulting to a healthy read that filled its page."""
    return {
        "limit": limit,
        "fetch_k": fetch_k,
        "candidates": candidates,
        "returned": returned,
        "excluded_kind": excluded_kind,
        "excluded_retention": excluded_retention,
        "excluded_window": excluded_window,
        "excluded_band": excluded_band,
    }


def configuration(
    *, when: datetime, metrics: dict[str, int | float | bool] | None = None
) -> EvaluationTrace:
    """One ``CONFIGURATION`` trace, as ``service/configuration.py`` stamps it."""
    return EvaluationTrace(
        kind=TraceKind.CONFIGURATION,
        seam="hub_startup",
        occurred_at=when,
        elapsed=None,
        outcome=TraceOutcome.OK,
        metrics={"observation_batch_size": 25} if metrics is None else metrics,
    )


#: ADR-0141 §3's two ruling seams, as the emitter labels them.
ADMIT = "notification_admit"
RECONSIDER = "notification_reconsider"

_INTERRUPT_CONDITIONS = (
    "condition_perishable",
    "condition_reach_interrupt",
    "condition_quiet_window",
    "condition_budget",
)


def ruled(  # noqa: PLR0913 — one keyword per key ADR-0141 §4 defines
    kind: NotificationDispositionKind,
    *,
    expired: int = 0,
    reach_off: int = 0,
    duplicate: int = 0,
    at_cap: int | None = None,
    perishable: int | None = None,
    reach_interrupt: int = 1,
    quiet_window: int = 1,
    budget: int = 1,
) -> dict[str, int]:
    """ADR-0141 §4's keys for one completed ruling, defaulting to a consistent one.

    Each default is what the merged policy would have written for that kind, so a
    suite wanting a shape the emitter cannot produce has to say so explicitly: an
    ``INTERRUPT`` holds all four interrupt conditions, a ``HOLD`` fails
    ``perishable`` alone — the ordinary case, a candidate declaring no expiry — and
    a ``DROP`` is at the cap and carries none of the interrupt half.
    """
    if at_cap is None:
        at_cap = int(kind is NotificationDispositionKind.DROP)
    if perishable is None:
        perishable = int(kind is not NotificationDispositionKind.HOLD)
    metrics = {
        "ruled_interrupt": int(kind is NotificationDispositionKind.INTERRUPT),
        "ruled_hold": int(kind is NotificationDispositionKind.HOLD),
        "ruled_drop": int(kind is NotificationDispositionKind.DROP),
        "condition_expired": expired,
        "condition_reach_off": reach_off,
        "condition_duplicate": duplicate,
        "condition_at_cap": at_cap,
    }
    if kind is not NotificationDispositionKind.DROP:
        metrics |= dict(
            zip(
                _INTERRUPT_CONDITIONS,
                (perishable, reach_interrupt, quiet_window, budget),
                strict=True,
            )
        )
    return metrics


def notification(
    *,
    when: datetime,
    seam: str = ADMIT,
    metrics: Mapping[str, int | float | bool] | None = None,
    outcome: TraceOutcome = TraceOutcome.OK,
    correlation: str | None = "c1",
) -> EvaluationTrace:
    """One ``NOTIFICATION`` trace, as ``memory/notification_traces.py`` emits it.

    No ``elapsed``: ADR-0141 §4 gives a notification trace ``held_seconds`` as its
    one duration, and the emitter observes no duration of the crossing at all.
    """
    return EvaluationTrace(
        kind=TraceKind.NOTIFICATION,
        seam=seam,
        occurred_at=when,
        elapsed=None,
        outcome=outcome,
        fault_class="RuntimeError"
        if outcome in (TraceOutcome.FAULT, TraceOutcome.REFUSED)
        else None,
        refs={} if correlation is None else {TraceRef.CORRELATION: correlation},
        metrics={} if metrics is None else metrics,
    )


def settled_marker(*, after: datetime = END, settling: timedelta = SETTLING) -> EvaluationTrace:
    """A trailing trace that puts the stream's extent past ``after + settling``.

    §4 defines memory precision only once the stream extends the settling period
    past the window's end, so a suite that wants a figure rather than a
    withholding has to say that the time has passed.
    """
    return operation("start", when=after + settling, correlation="settled")
