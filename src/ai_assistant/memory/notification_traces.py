"""ADR-0141 §3's ruling seam: one ``NOTIFICATION`` trace per notification ruling.

§3 names two seams and both are `memory`'s — ``NotificationStore.admit`` and
``NotificationStore.reconsider``, "ADR-0130 §3's atomic act, in both the shapes it
takes". This module holds what they share: the seam labels, §4's eleven metric
keys, the reading that turns one ruling into those keys, and the envelope that
appends it.

**The store emits rather than the writer stage, and §3 forces that twice over.**
The facts §4 records exist only inside ADR-0130 §3's transaction — the duplicate
lookup, the cap check and the budget read are the store's own — and the
reconsideration path does not pass through the writer stage at all, so a
writer-sited emitter "would miss every ruling that is not a first offer".
``orchestration/notifications.py`` is refused explicitly by §3 and by the ADR's
Alternatives; nothing here is reachable from there.

**Everything here is subordinate to the ruling it observes** (§3, ADR-0119 §5).
No ruling fails, retries, is rolled back or changes its disposition because a
trace could not be written, and no trace is written inside the ruling
transaction: the store calls this module only once the act has committed. What a
lost trace costs is the Tier 2 log record :func:`~ai_assistant.memory.traces.dropped`
writes, which is why that function is shared with the two ADR-0119 §8 emitters
rather than copied — a second implementation of one ADR-0119 §5 record inside one
package is a second thing to keep honest.

**The instant is the caller's and never this module's** (§3). ``occurred_at`` is
"the single clock reading taken inside ADR-0130 §3's atomic act — the ruling
instant, the one §4 subtracts ``admitted_at`` from — and never the instant of
emission". So this module reads no clock: the emission is deliberately later than
the act, and an emitter stamping its own reading would put a ruling near a window
boundary on the wrong side of it, which is exactly the divergence ADR-0120 §1
exists to prevent. A crossing that obtained no reading at all emits nothing and is
logged as a lost trace instead (§3).

**Nothing about the notification travels** (§4's last clause). Every string this
module can put in a trace is a literal constant below, a ``StrEnum`` member from
``core/types.py``, an opaque correlation id, or an exception class's name through
ADR-0119 §3's total conversion. No id, no candidate key, no producer, no class, no
summary, no detail, no expiry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ai_assistant.core.correlation import current_correlation
from ai_assistant.core.types import (
    INTERRUPT_CONDITIONS,
    EvaluationTrace,
    NotificationCondition,
    NotificationDispositionKind,
    NotificationReach,
    TraceKind,
    TraceOutcome,
    TraceRef,
    fault_class_of,
)
from ai_assistant.memory.traces import REFUSALS, dropped

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from ai_assistant.core.protocols import TraceSink
    from ai_assistant.core.types import (
        NotificationCandidate,
        NotificationDisposition,
        NotificationPreferences,
    )

# --- the seam labels (§3: literal constants in the emitting module) -----------

#: ``NotificationStore.admit`` — one offer ruled, one trace (§3).
SEAM_ADMIT: Final = "notification_admit"

#: ``NotificationStore.reconsider`` — one held record re-ruled, one trace (§3).
#: A call that found nothing to rule emits none: no ruling was made.
SEAM_RECONSIDER: Final = "notification_reconsider"

# --- §4's metric keys ---------------------------------------------------------

#: One literal key per disposition kind, and a completed ruling carries **all
#: three** — each ``0`` or ``1``, written by one statement so they are observed
#: and lost together (§4). Their sum over §5's ruling population is §6's
#: interruption-share denominator, which is why ADR-0119 §5's rule is satisfied
#: without an external count: one statement writes the numerator and the
#: denominator, so one loss takes both.
#:
#: A mapping of literals rather than an ``f"ruled_{kind.value}"``, for
#: :data:`~ai_assistant.memory.traces.DECISION_METRICS`' reason: §4's first clause
#: makes a metric key "a literal constant written in the emitting module", and a
#: key composed at runtime is the shape that clause keeps out even where what it
#: is composed from is harmless. Totality over the enumeration is asserted by
#: test, so a member added later fails loudly here instead of dropping a count.
DISPOSITION_METRICS: Final[Mapping[NotificationDispositionKind, str]] = {
    NotificationDispositionKind.INTERRUPT: "ruled_interrupt",
    NotificationDispositionKind.HOLD: "ruled_hold",
    NotificationDispositionKind.DROP: "ruled_drop",
}

#: One literal key per condition, carrying ``1`` when the proposition the member
#: names held at the ruling instant and ``0`` when it did not — **the
#: enumeration's own propositions, not their negations** (§4). Two of them are
#: deliberately not opposites: a candidate declaring no expiry at all makes both
#: ``EXPIRED`` and ``PERISHABLE`` false, which is the ordinary case and why
#: ADR-0130 §5 holds such a candidate rather than dropping it.
#:
#: **The two halves have different provenances and neither side can supply the
#: other's** (§4). The four :data:`~ai_assistant.core.types.DROP_CONDITIONS` are
#: observed by the store, out of the arguments it handed the policy; the four
#: :data:`~ai_assistant.core.types.INTERRUPT_CONDITIONS` are read off the
#: disposition and never recomputed, because ``Settings.timezone`` is a
#: construction-time property of the *policy* (ADR-0130 §4) and no quiet window
#: can be evaluated from here at all. :func:`ruling_metrics` is where the split is
#: implemented.
CONDITION_METRICS: Final[Mapping[NotificationCondition, str]] = {
    NotificationCondition.EXPIRED: "condition_expired",
    NotificationCondition.REACH_OFF: "condition_reach_off",
    NotificationCondition.DUPLICATE: "condition_duplicate",
    NotificationCondition.AT_CAP: "condition_at_cap",
    NotificationCondition.PERISHABLE: "condition_perishable",
    NotificationCondition.REACH_INTERRUPT: "condition_reach_interrupt",
    NotificationCondition.QUIET_WINDOW: "condition_quiet_window",
    NotificationCondition.BUDGET: "condition_budget",
}

#: How long the record had been held when a reconsideration interrupted it: the
#: ruling instant less its ``admitted_at``, in seconds. Carried by a trace at
#: :data:`SEAM_RECONSIDER` whose ruling was ``INTERRUPT`` and **by no other** (§4).
#:
#: **It is what a join would otherwise have cost.** Finding a hold from its later
#: interrupt would need a ``TraceRef`` member — a second ``core/types.py``
#: addition at ADR-0119 §13e's full price — plus an id in the stream that
#: ADR-0120 §10 then forbids the report to print. The store already holds
#: ``admitted_at`` on the record it is re-ruling, so a subtraction beats a join.
#:
#: **Not a count**, and §4 says so: it is a finite, non-negative ``int`` or
#: ``float`` that is not a ``bool``, where every other key here is a count.
HELD_SECONDS: Final = "held_seconds"


def ruling_metrics(  # noqa: PLR0913 — one parameter per quantity §4 reads, each from its own source
    *,
    candidate: NotificationCandidate,
    ruling: NotificationDisposition,
    preferences: NotificationPreferences,
    duplicate: bool,
    at_cap: bool,
    now: datetime,
    admitted_at: datetime | None = None,
) -> dict[str, int | float]:
    """Read one completed ruling into §4's metric keys.

    Called **after** the ruling has committed and never before: a disposition the
    transaction rolled back is not a ruling — no record was written and no unit of
    budget was spent — so it carries none of these keys and enters no population
    (§3). The keys the caller omits are the observation ADR-0119 §3 makes them:
    absent means the quantity was not reached.

    Args:
        candidate: The proposal that was ruled on. Read for its expiry and its
            class, and for nothing that travels.
        ruling: What the policy decided. Its ``kind`` writes the three disposition
            keys and its ``failed`` set is the *whole* source of the four
            interrupt conditions — ``NotificationDisposition`` refuses at
            construction any ``HOLD`` whose ``failed`` is not the complete ordered
            failing set, so the recovery rests on the contract and holds for a
            custom ``NotificationPolicy`` and not merely for the default one.
        preferences: The standing settings the store read inside the act, for the
            reach level in force on this candidate's class.
        duplicate: The boolean the store computed and handed the policy (§4).
        at_cap: The boolean the store computed and handed the policy (§4).
        now: The ruling instant — the same reading the trace's ``occurred_at``
            carries, so the store's reading of a condition and the policy's are
            one reading (ADR-0130 §9's determinism clause).
        admitted_at: When the record being re-ruled was admitted, supplied by the
            reconsideration seam alone. :data:`HELD_SECONDS` is carried exactly
            when this is present *and* the ruling was ``INTERRUPT``; the admission
            seam passes nothing, which is what keeps §4's placement rule true at
            the one call site that could break it.

    Returns:
        The metric mapping for a completed ruling.
    """
    # One statement, so the three are observed and lost together (§4, ADR-0119 §5).
    metrics: dict[str, int | float] = {
        key: int(kind is ruling.kind) for kind, key in DISPOSITION_METRICS.items()
    }
    # The drop half: every one of the four is read off an argument the store
    # handed the policy, and all four are carried on every completed ruling —
    # including one the first of them decided, because the policy computes all
    # four before it tests them in order (§4).
    metrics.update(
        {
            CONDITION_METRICS[NotificationCondition.EXPIRED]: int(
                candidate.expires_at is not None and not candidate.is_perishable_at(now)
            ),
            CONDITION_METRICS[NotificationCondition.REACH_OFF]: int(
                preferences.reach_for(candidate.notification_class) is NotificationReach.OFF
            ),
            CONDITION_METRICS[NotificationCondition.DUPLICATE]: int(duplicate),
            CONDITION_METRICS[NotificationCondition.AT_CAP]: int(at_cap),
        }
    )
    if ruling.kind is not NotificationDispositionKind.DROP:
        # The interrupt half, read off the disposition and never recomputed (§4).
        # An `INTERRUPT` carries `1` for all four because ADR-0130 §5 rules that
        # kind exactly when every one of them holds, which is the same statement
        # as "its failed set is empty"; a `HOLD` carries `0` for each member of
        # that set and `1` for every other. A `DROP` carries none of them: the
        # ruling stopped at the first drop condition and the policy never
        # evaluated these.
        failed = set(ruling.failed)
        metrics.update(
            {
                CONDITION_METRICS[condition]: int(condition not in failed)
                for condition in INTERRUPT_CONDITIONS
            }
        )
    if admitted_at is not None and ruling.kind is NotificationDispositionKind.INTERRUPT:
        metrics[HELD_SECONDS] = (now - admitted_at).total_seconds()
    return metrics


class NotificationTraces:
    """Appends one ``NOTIFICATION`` trace per crossing of a ruling seam (§3).

    One instance per store. The kind is fixed rather than passed, for
    :class:`~ai_assistant.memory.traces.MemoryTraces`' reason: it is the axis
    ADR-0119 §3 states the tier discipline along, and a caller that could choose
    it could put a ruling's keys on another kind.
    """

    def __init__(self, *, sink: TraceSink) -> None:
        """Wire the emitter to the trace store's append seam.

        Args:
            sink: A :class:`~ai_assistant.core.protocols.TraceSink` and never a
                ``TraceStore``, because ADR-0119 §7 gives an emitter the write and
                withholds the walk: "no component of the request pipeline… holds a
                seam carrying the walk, and none reads a trace back". The
                narrowing is this annotation.
        """
        self._sink = sink

    async def ruled(
        self, seam: str, *, occurred_at: datetime, metrics: Mapping[str, int | float]
    ) -> None:
        """Record a ruling that committed.

        Args:
            seam: Which crossing this is — a literal constant above.
            occurred_at: The ruling instant, read inside the atomic act.
            metrics: §4's keys, as :func:`ruling_metrics` read them.
        """
        await self._record(seam, occurred_at=occurred_at, outcome=TraceOutcome.OK, metrics=metrics)

    async def failed(self, seam: str, *, occurred_at: datetime | None, error: Exception) -> None:
        """Record a crossing that raised before its ruling committed (§3).

        The trace carries its outcome and its fault class and **none** of §4's
        metric keys, on both sides of the ruling: a fault before
        ``NotificationPolicy.rule`` was called, and a write or a commit that
        failed after it returned. A disposition the transaction rolled back is not
        a ruling — no record was written and no unit of budget was spent — so
        counting its keys would put an interruption in §6's numerator that no
        record reflects.

        **A crossing that obtained no clock reading emits nothing**, whichever way
        the reading failed to arrive: ``checked_clock`` lets an exception from the
        injected callable propagate unwrapped and refuses a non-conforming reading
        with ``ClockReadingError``, and either way ``occurred_at`` has no instant
        to stamp. It is logged as a lost trace instead — never dropped silently,
        which ADR-0119 §5 refuses outright, and never stamped with a wall-clock
        reading, which would put a fabricated instant in a window and move a rate.

        **A cancellation never reaches here at all** (§3, ADR-0119 §3, ADR-0060
        §1). The store re-raises it before deciding any outcome or fault class, so
        nothing is written for one: no trace, and no lost-trace record either —
        the precedence §3 states, because ADR-0119 §5's record would name the
        failure's class and ADR-0119 §3 forbids deriving one from a cancellation.
        That is why this method takes an ``Exception`` and not a
        ``BaseException``.

        Args:
            seam: Which crossing this is — a literal constant above.
            occurred_at: The ruling instant if the crossing reached one, and
                ``None`` where the clock never read.
            error: What the crossing raised.
        """
        if occurred_at is None:
            dropped(TraceKind.NOTIFICATION, seam, error)
            return
        await self._record(
            seam,
            occurred_at=occurred_at,
            outcome=TraceOutcome.REFUSED if isinstance(error, REFUSALS) else TraceOutcome.FAULT,
            metrics={},
            fault_class=fault_class_of(error),
        )

    async def _record(
        self,
        seam: str,
        *,
        occurred_at: datetime,
        outcome: TraceOutcome,
        metrics: Mapping[str, int | float],
        fault_class: str | None = None,
    ) -> None:
        """Build the trace and append it, letting nothing out (ADR-0119 §5, §3).

        Construction is guarded as well as emission, because ADR-0119 §2's and
        §3's constraints are enforced *at construction*: a metric key that is not
        a label, a non-finite value. Each would be a bug in this module, and each
        must cost a trace rather than a ruling.

        **No correlation scope is opened here** (§3, ADR-0119 §4). The ambient
        value is read and recorded, or the reference is omitted where there is
        none — a scheduler tick outside an operation, a test driving the store
        directly. No measure §6 or §7 defines joins on it.

        **No duration is observed.** ADR-0141 §4 fixes what a notification trace
        carries and the one duration in it is :data:`HELD_SECONDS`, which is a
        property of the record rather than of the crossing. An ``elapsed``
        measured here could not be read beside ``occurred_at`` in any case: the
        instant is the *ruling's* and the crossing began before it, so the two
        would not bound one interval the way ADR-0119 §8's seams make them.

        Args:
            seam: Which crossing this is.
            occurred_at: The ruling instant.
            outcome: What the crossing did.
            metrics: What it observed — empty on the fault path.
            fault_class: The class of the exception that decided a failing
                outcome, through ADR-0119 §3's total conversion; ``None``
                otherwise.
        """
        correlation = current_correlation()
        try:
            trace = EvaluationTrace(
                kind=TraceKind.NOTIFICATION,
                seam=seam,
                occurred_at=occurred_at,
                outcome=outcome,
                fault_class=fault_class,
                refs={} if correlation is None else {TraceRef.CORRELATION: correlation},
                metrics=metrics,
            )
        # Broad by design: §3 makes a malformed trace a lost trace, not a failed ruling.
        except Exception as error:
            dropped(TraceKind.NOTIFICATION, seam, error)
            return
        try:
            await self._sink.emit(trace)
        # Broad by design: ADR-0119 §7 says a conforming sink cannot raise here, and
        # §3 says what to do if one does anyway.
        except Exception as error:
            dropped(TraceKind.NOTIFICATION, seam, error)


__all__ = [
    "CONDITION_METRICS",
    "DISPOSITION_METRICS",
    "HELD_SECONDS",
    "SEAM_ADMIT",
    "SEAM_RECONSIDER",
    "NotificationTraces",
    "ruling_metrics",
]
