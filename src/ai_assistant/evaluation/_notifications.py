"""ADR-0141's reader: §5's classifier, §6's two measures and §7's five diagnostics.

ADR-0141 §1 makes every figure here "a rate over ruling events in the trace
stream", computed "from ``EvaluationTrace`` records alone, over an explicit
half-open window of ``occurred_at``". No notification store is opened — ADR-0120
§10's one-store rule "is obeyed rather than excepted, and this ADR opens no seventh
door" — so nothing in this module knows that ``notifications.db`` exists.

**The unit is a ruling, never a record** (§1). "The same notification ruled three
times contributes three events, and a record that was never ruled contributes
none." That is what removes the trailing-edge bias a record-shaped measure would
have inherited, and it is why §8 gives these figures no settling period: "a
ruling's numerator is the ruling itself", so a ruling made one second before the
window closed contributes exactly what one made on the first day does.

**Four states, tested in order, disjoint and exhaustive** (§5). The order is not
presentation: "a trace carrying ``ruled_interrupt = 2`` satisfies 'carries all
three disposition keys' and also fails the sum rule; a condition key of ``-1`` is
both a bad count and a bad condition value. Stated as independent predicates, each
such trace is admissible under one clause and excluded under another, and the
report's own exclusion counts double." :func:`read` applies the four tests in §5's
sequence and returns the first that decides.

**Nothing here reads ``elapsed``** (§12). A notification trace carries
``held_seconds`` as its one duration, which is a property of the *record* rather
than of the crossing; extending ADR-0120 §7's per-seam latency summary across kinds
"is not proposed", and the emitter measures no duration to extend it with.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import TYPE_CHECKING

from ai_assistant.core.types import (
    NotificationCondition,
    NotificationDispositionKind,
    TraceOutcome,
)
from ai_assistant.evaluation._figures import (
    ConditionIncidence,
    Distribution,
    NotificationFigures,
    NotificationHealth,
    Rate,
)
from ai_assistant.evaluation._stream import is_count
from ai_assistant.evaluation._vocabulary import (
    DROP_CONDITION_KEYS,
    HELD_SECONDS,
    INTERRUPT_CONDITION_KEYS,
    NOTIFICATION_ADMIT_SEAM,
    NOTIFICATION_CONDITION_KEYS,
    NOTIFICATION_COUNT_KEYS,
    NOTIFICATION_DISPOSITION_KEYS,
    NOTIFICATION_METRIC_KEYS,
    NOTIFICATION_RECONSIDER_SEAM,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ai_assistant.core.types import EvaluationTrace

#: The one condition key §6's duplicate share reads, over the well-formed offers.
_DUPLICATE = NOTIFICATION_CONDITION_KEYS[NotificationCondition.DUPLICATE]

#: The two §5 names directly, because they are the pair that is **not** opposites.
_EXPIRED = NOTIFICATION_CONDITION_KEYS[NotificationCondition.EXPIRED]
_PERISHABLE = NOTIFICATION_CONDITION_KEYS[NotificationCondition.PERISHABLE]


class NotificationState(StrEnum):
    """Which of §5's four states a ``NOTIFICATION`` trace is in.

    Exhaustive and disjoint by construction: :func:`read` applies §5's four tests
    in order and the first that applies decides, "so no trace is counted under two
    of them and none is left unclassified by any implementation".
    """

    INCOMPLETE = "incomplete"
    """None of §4's twelve keys: a crossing that raised before the ruling
    committed (§3). "It records a crossing that raised before the ruling
    committed, it enters no population, and the report counts it apart from the
    two faults below because it is not one." Named rather than folded into
    *malformed* because it is the ordinary fault path, and "counting it beside two
    genuine faults would make an outage look like an emitter bug"."""

    MALFORMED = "malformed"
    """A key set no emitter in this tree can write. The trace "cannot say what was
    ruled" or a population's denominator "would silently shrink", so it leaves
    every population."""

    COUNTER_INCONSISTENT = "counter_inconsistent"
    """Every key present and admissible, and the values disagree. A *localised*
    fault: the conditions "are written by a different statement from the
    disposition keys, so the trace can still say truthfully that an interruption
    happened while being untrustworthy about why". It stays in the ruling
    population and leaves the two figures that read a condition key."""

    WELL_FORMED = "well_formed"
    """In none of the three above."""

    @property
    def in_population(self) -> bool:
        """Whether §5 puts this state in the ruling population.

        "Over a window ``W``, the **ruling population** is every well-formed or
        counter-inconsistent trace whose ``occurred_at`` lies in ``W``."
        """
        return self in (NotificationState.WELL_FORMED, NotificationState.COUNTER_INCONSISTENT)


class Seam(StrEnum):
    """Which of §5's two sub-populations a ruling trace's seam puts it in.

    A third answer — *unclassified* — is the absence of a member rather than a
    member, exactly as ADR-0120 §3's seam sets do it: "a trace whose seam is
    neither of those two stays in the ruling population, enters neither
    sub-population, and the report names each unclassified seam it met".
    """

    OFFER = "offer"
    RECONSIDERATION = "reconsideration"


def seam_of(trace: EvaluationTrace) -> Seam | None:
    """Which sub-population ``trace``'s seam names, or ``None`` for neither.

    Two seam labels rather than a denylist, on ADR-0120 §3's discipline: "a later
    lane may add a third ruling seam, and defaulting an unrecognised one into the
    offer or the reconsideration population would silently absorb it into a
    diagnostic. The count that rises is the prompt to classify it."

    Args:
        trace: A ``NOTIFICATION`` trace.

    Returns:
        The sub-population, or ``None`` when the seam is on neither list.
    """
    if trace.seam == NOTIFICATION_ADMIT_SEAM:
        return Seam.OFFER
    if trace.seam == NOTIFICATION_RECONSIDER_SEAM:
        return Seam.RECONSIDERATION
    return None


@dataclass(frozen=True, slots=True)
class Ruling:
    """One ``NOTIFICATION`` trace read into everything §6 and §7 count.

    Attributes:
        state: Which of §5's four states decided it.
        seam: Which sub-population its seam names, or ``None`` when neither does.
        ruled: What the disposition keys say was decided, or ``None`` where they
            could not be read. Present exactly when :attr:`state` is in the ruling
            population.
        conditions: Every condition key the trace carries, with its value. Read
            only for the well-formed, which is the population §6's duplicate share
            and §7's condition incidence are defined over.
        held_seconds: The latency §7's distribution reads, or ``None``. Present
            only where §4 both requires the key and admits its value.
        misplaced: Whether §7 calls this trace's ``held_seconds`` misplaced —
            "carrying it where §4 forbids it, or carrying an inadmissible value or
            none where §4 requires it". Consulted only for members of the ruling
            population, whose traces are the only ones "in every other population"
            for the value to stay out of.
    """

    state: NotificationState
    seam: Seam | None
    ruled: NotificationDispositionKind | None
    conditions: dict[str, int]
    held_seconds: float | None
    misplaced: bool

    @property
    def interrupted(self) -> bool:
        """Whether ``ruled_interrupt`` is ``1`` — §6's and §7's numerator."""
        return self.ruled is NotificationDispositionKind.INTERRUPT


def read(trace: EvaluationTrace) -> Ruling:
    """Apply §5's four tests in order and read what the trace carries.

    Args:
        trace: A ``NOTIFICATION`` trace, inside the window or outside it.

    Returns:
        Its state and, where the state admits it, what it says.
    """
    seam = seam_of(trace)
    metrics = trace.metrics
    if not any(key in metrics for key in NOTIFICATION_METRIC_KEYS):
        # §5's first test, over §4's **whole** key set and not the dispositions
        # alone: a trace bearing any of those keys reached the ruling, "so it is a
        # fault of the emitter and belongs to the tests below".
        return _undecided(NotificationState.INCOMPLETE, seam)
    ruled = _malformation(trace)
    if ruled is None:
        return _undecided(NotificationState.MALFORMED, seam)
    conditions = {
        key: int(metrics[key]) for key in NOTIFICATION_CONDITION_KEYS.values() if key in metrics
    }
    state = (
        NotificationState.COUNTER_INCONSISTENT
        if _counter_inconsistent(ruled, conditions)
        else NotificationState.WELL_FORMED
    )
    held, misplaced = _held_seconds(trace, seam=seam, ruled=ruled)
    return Ruling(
        state=state,
        seam=seam,
        ruled=ruled,
        conditions=conditions,
        held_seconds=held,
        misplaced=misplaced,
    )


def _undecided(state: NotificationState, seam: Seam | None) -> Ruling:
    """A trace §5 excluded before anything could be read off it.

    Its ``held_seconds`` is not *misplaced*: §7's misplacement is a statement about
    a trace that "stays in every other population", and this one is in none.
    """
    return Ruling(
        state=state, seam=seam, ruled=None, conditions={}, held_seconds=None, misplaced=False
    )


def _malformation(trace: EvaluationTrace) -> NotificationDispositionKind | None:
    """What was ruled, or ``None`` when §5's second test calls the trace malformed.

    Every disjunct of §5's malformed clause is here, split across this function and
    the two below it. They are evaluated in an order that lets each rest on the one
    before rather than in §5's listing order — which costs nothing, because the
    disjuncts share one verdict: the disposition keys must all be present before
    "the ruling" is a thing to speak of, and each value must be a count before its
    sum means anything.

    Args:
        trace: A trace §5's first test did not decide.

    Returns:
        The disposition the three keys name, or ``None`` for malformed.
    """
    metrics = trace.metrics
    present = [key in metrics for key in NOTIFICATION_DISPOSITION_KEYS.values()]
    if not all(present) or not _admissible(trace):
        return None
    if sum(int(metrics[key]) for key in NOTIFICATION_DISPOSITION_KEYS.values()) != 1:
        return None
    # Three non-negative integers summing to one: exactly one of them is the ruling.
    ruled = next(
        kind for kind, key in NOTIFICATION_DISPOSITION_KEYS.items() if int(metrics[key]) == 1
    )
    return ruled if _conditions_placed(trace, ruled) else None


def _admissible(trace: EvaluationTrace) -> bool:
    """Whether every key §4 constrains carries a value §4 admits.

    Two of §5's malformed disjuncts, and they overlap deliberately: a condition key
    of ``-1`` "is both a bad count and a bad condition value". Answering them
    together is what keeps the overlap from becoming two exclusion counts for one
    trace — the property §5's ordering exists to supply.

    Args:
        trace: A trace §5's first test did not decide.

    Returns:
        Whether every present count is a count and every present condition is
        ``0`` or ``1``.
    """
    metrics = trace.metrics
    counts_admit = all(is_count(metrics[key]) for key in NOTIFICATION_COUNT_KEYS if key in metrics)
    return counts_admit and all(
        int(metrics[key]) in (0, 1)
        for key in NOTIFICATION_CONDITION_KEYS.values()
        if key in metrics
    )


def _conditions_placed(trace: EvaluationTrace, ruled: NotificationDispositionKind) -> bool:
    """Whether §4's two placement rules hold of the condition keys.

    All four drop conditions on **every** completed ruling, "including one dropped
    by the first, because the policy computes all four before it tests them in
    order"; and the four interrupt conditions on every ruling that was not ``DROP``
    and on no ruling that was — a ``DROP`` "stopped at the first drop condition and
    the policy never evaluated these".

    A missing key is malformed rather than merely uncounted, which is §5's second
    closed overlap: under a rule checking consistency only where keys are present, a
    ``HOLD`` arriving without ``condition_budget`` "would have entered the condition
    incidence, shrinking that one condition's denominator while appearing in no
    exclusion count at all".

    Args:
        trace: A trace whose disposition keys were read.
        ruled: What they named.

    Returns:
        Whether the condition keys are placed as §4 requires.
    """
    metrics = trace.metrics
    if any(key not in metrics for key in DROP_CONDITION_KEYS):
        return False
    interrupt_half = [key in metrics for key in INTERRUPT_CONDITION_KEYS]
    if ruled is NotificationDispositionKind.DROP:
        return not any(interrupt_half)
    return all(interrupt_half)


def _counter_inconsistent(ruled: NotificationDispositionKind, conditions: dict[str, int]) -> bool:
    """Whether §5's third test finds the present keys disagreeing with one another.

    The last disjunct is ADR-0130 §5's ordering read as an invariant and is "the one
    a reader is most likely to leave out": that section evaluates the four drop
    conditions **first**, "each yielding ``DROP`` naming itself", so a satisfied drop
    condition and a ruling that is not ``DROP`` cannot both have happened. Without
    it "such a trace passes every other test, enters the ruling population as
    well-formed, and counts a refusal as an interruption, moving the one measure §6
    exists for".

    Args:
        ruled: What the disposition keys named.
        conditions: The condition keys the trace carries, all admissible.

    Returns:
        Whether the trace is counter-inconsistent.
    """
    if conditions.get(_EXPIRED) == 1 and conditions.get(_PERISHABLE) == 1:
        # Not opposites: a candidate declaring no expiry at all makes both false,
        # "which is exactly why ADR-0130 §5 holds it rather than dropping it". What
        # is impossible is both holding at once.
        return True
    interrupt_half = [conditions[key] for key in INTERRUPT_CONDITION_KEYS if key in conditions]
    drop_half = [conditions[key] for key in DROP_CONDITION_KEYS]
    if ruled is NotificationDispositionKind.INTERRUPT and not all(interrupt_half):
        return True
    if ruled is NotificationDispositionKind.DROP:
        return not any(drop_half)
    if ruled is NotificationDispositionKind.HOLD and all(interrupt_half):
        return True
    return any(drop_half)


def _held_seconds(
    trace: EvaluationTrace, *, seam: Seam | None, ruled: NotificationDispositionKind
) -> tuple[float | None, bool]:
    """§4's placement rule for ``held_seconds``, and §7's misplacement count.

    §4 carries the key on "a trace at ``notification_reconsider`` whose ruling was
    ``INTERRUPT``" and on no other. So there are two ways to be misplaced and §7
    names both: the key where §4 forbids it, and "an inadmissible value or none
    where §4 requires it".

    Admissibility is §4's own four properties — a finite, non-negative ``int`` or
    ``float`` that is not a ``bool``. ADR-0119 §3 already refuses ``NaN`` and the
    infinities at construction, so the finiteness conjunct holds of every trace this
    tree can hydrate; it is written because §4 states it, so a reader checking this
    function against the clause finds all four rather than three and a footnote.

    Args:
        trace: A trace that reached §5's third test.
        seam: Which sub-population its seam names.
        ruled: What the disposition keys named.

    Returns:
        The latency §7 may read, and whether §7 counts this trace as misplaced.
    """
    required = seam is Seam.RECONSIDERATION and ruled is NotificationDispositionKind.INTERRUPT
    value = trace.metrics.get(HELD_SECONDS)
    if not required:
        return None, value is not None
    if value is None or isinstance(value, bool) or not isfinite(value) or value < 0:
        return None, True
    return float(value), False


class Tally:
    """Accumulates one part's ruling population as the walk meets it.

    One instance per part of the window, plus nothing for the whole: §8 needs the
    window entire as well, and every population here is a disjoint union over the
    parts, so the whole is the parts folded together by :meth:`absorb`.
    """

    def __init__(self) -> None:
        self.walked = 0
        self.states: dict[NotificationState, int] = {}
        self.unclassified = 0
        self.unclassified_seams: set[str] = set()
        self.misplaced = 0
        self.not_ok = 0
        self.dispositions: dict[NotificationDispositionKind, int] = {}
        self.reconsidered_interrupts = 0
        self.offers = 0
        self.duplicate_offers = 0
        self.carried: dict[str, int] = {}
        self.held: dict[str, int] = {}
        self.latencies: list[float] = []

    def add(self, trace: EvaluationTrace, ruling: Ruling) -> None:
        """Fold one ``NOTIFICATION`` trace inside this part into every population.

        Args:
            trace: The trace, whose ``occurred_at`` lies in this part.
            ruling: What :func:`read` made of it.
        """
        self.walked += 1
        self.states[ruling.state] = self.states.get(ruling.state, 0) + 1
        if trace.outcome is not TraceOutcome.OK:
            self.not_ok += 1
        if not ruling.state.in_population or ruling.ruled is None:
            return
        if ruling.seam is None:
            self.unclassified += 1
            self.unclassified_seams.add(trace.seam)
        if ruling.misplaced:
            self.misplaced += 1
        self.dispositions[ruling.ruled] = self.dispositions.get(ruling.ruled, 0) + 1
        if ruling.seam is Seam.RECONSIDERATION and ruling.interrupted:
            self.reconsidered_interrupts += 1
            if ruling.held_seconds is not None:
                self.latencies.append(ruling.held_seconds)
        if ruling.state is not NotificationState.WELL_FORMED:
            # §5: the duplicate share and the condition incidence are computed over
            # the well-formed alone, because both read a condition key and that is
            # exactly what a counter-inconsistent trace is untrustworthy about.
            return
        for key, value in ruling.conditions.items():
            self.carried[key] = self.carried.get(key, 0) + 1
            self.held[key] = self.held.get(key, 0) + value
        if ruling.seam is Seam.OFFER:
            self.offers += 1
            self.duplicate_offers += ruling.conditions.get(_DUPLICATE, 0)

    def absorb(self, other: Tally) -> None:
        """Fold another part's sums in, which is how the whole window is formed."""
        self.walked += other.walked
        self.unclassified += other.unclassified
        self.unclassified_seams |= other.unclassified_seams
        self.misplaced += other.misplaced
        self.not_ok += other.not_ok
        self.reconsidered_interrupts += other.reconsidered_interrupts
        self.offers += other.offers
        self.duplicate_offers += other.duplicate_offers
        self.latencies += other.latencies
        for state, count in other.states.items():
            self.states[state] = self.states.get(state, 0) + count
        for kind, count in other.dispositions.items():
            self.dispositions[kind] = self.dispositions.get(kind, 0) + count
        for key, count in other.carried.items():
            self.carried[key] = self.carried.get(key, 0) + count
        for key, count in other.held.items():
            self.held[key] = self.held.get(key, 0) + count

    def figures(self, *, start: datetime, end: datetime) -> NotificationFigures:
        """Form §6's measures and §7's diagnostics from what was accumulated.

        Args:
            start: The part's inclusive start.
            end: The part's exclusive end.

        Returns:
            The figures.
        """
        interrupts = self.dispositions.get(NotificationDispositionKind.INTERRUPT, 0)
        holds = self.dispositions.get(NotificationDispositionKind.HOLD, 0)
        drops = self.dispositions.get(NotificationDispositionKind.DROP, 0)
        return NotificationFigures(
            start=start,
            end=end,
            interruption=Rate(numerator=interrupts, denominator=interrupts + holds + drops),
            duplicate=Rate(numerator=self.duplicate_offers, denominator=self.offers),
            interrupts=interrupts,
            holds=holds,
            drops=drops,
            incidence=tuple(
                ConditionIncidence(
                    condition=condition,
                    key=key,
                    carried=self.carried.get(key, 0),
                    held=self.held.get(key, 0),
                )
                for condition, key in NOTIFICATION_CONDITION_KEYS.items()
            ),
            held_latency=Distribution.over(self.latencies),
            held_first=Rate(numerator=self.reconsidered_interrupts, denominator=interrupts),
            health=NotificationHealth(
                walked=self.walked,
                well_formed=self.states.get(NotificationState.WELL_FORMED, 0),
                incomplete=self.states.get(NotificationState.INCOMPLETE, 0),
                malformed=self.states.get(NotificationState.MALFORMED, 0),
                counter_inconsistent=self.states.get(NotificationState.COUNTER_INCONSISTENT, 0),
                unclassified=self.unclassified,
                unclassified_seams=tuple(sorted(self.unclassified_seams)),
                misplaced_held_seconds=self.misplaced,
                not_ok=self.not_ok,
            ),
        )


__all__ = ["NotificationState", "Ruling", "Seam", "Tally", "read", "seam_of"]
