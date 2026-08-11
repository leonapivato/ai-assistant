"""The deterministic ruling of ADR-0130 §4 and §5, as production code.

**No model is consulted and none may be** (§11). An interruption a model chose
cannot be explained to the user who received it, cannot be tested
deterministically, and cannot run when no provider is reachable — which is
exactly when a resident process is still noticing. Every answer here is a
function of the arguments and of this object's one construction-time property,
the timezone quiet windows are read in.

**Why this lives beside the notification store rather than in `orchestration`.**
It is a concrete implementation of a `core` Protocol, injected by the composition
root, which is what every other policy in this tree is —
:class:`~ai_assistant.memory.policy.DefaultMemoryPolicy` sits beside the store it
rules for, and this is the same arrangement for the same reason. The package
choice is ``notification_store``'s: the architecture map names no
``notifications`` subsystem, and minting a top-level package is an ADR's decision
rather than an implementation lane's.

**It is a near-duplicate of :class:`~ai_assistant.testing.FakeNotificationPolicy`,
deliberately.** ``ai_assistant.testing`` may not be imported by production code —
``lint-imports`` fails the gate on the edge — and a subsystem may not import
another's module either (golden rule 1), so a shared home would have to be
``core``, which is contract surface rather than a place for concrete helpers.
That is the same boundary cost ``memory/_transactions.py`` records for its own
four copies, and #563 holds the general question. What keeps the two honest is
that both are held to the *same* shared conformance suite
(``tests/core/notification_contract.py``), which is the mechanism the duplication
is safe under.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ai_assistant.core.types import (
    DROP_CONDITIONS,
    INTERRUPT_CONDITIONS,
    MINUTES_IN_A_DAY,
    TIME_RESOLVED_CONDITIONS,
    NotificationCondition,
    NotificationDisposition,
    NotificationDispositionKind,
    NotificationReach,
    minute_of_day,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ai_assistant.core.types import NotificationCandidate, NotificationPreferences


def _next_due(
    failed: Iterable[NotificationCondition],
    *,
    quiet_until: datetime | None,
    budget_frees_at: datetime | None,
) -> datetime | None:
    """The earliest instant at which **every** failing condition could next hold.

    ``None`` where any failing condition is not one time alone resolves — the
    reach level and an absent expiry are each such a condition — and ``None``
    again where a nominally time-resolvable condition has no instant to offer,
    which a budget of zero and an all-day quiet each are (ADR-0130 §5).

    Args:
        failed: The conditions that failed at the ruling.
        quiet_until: When the covering quiet stretch ends, if one covers.
        budget_frees_at: When the budget window next frees a unit, if it will.

    Returns:
        The due instant, or ``None``.
    """
    conditions = set(failed)
    if not conditions <= TIME_RESOLVED_CONDITIONS:
        return None
    instants: list[datetime] = []
    if NotificationCondition.QUIET_WINDOW in conditions:
        if quiet_until is None:
            return None  # quiet covers every minute of the day, so time never lifts it
        instants.append(quiet_until)
    if NotificationCondition.BUDGET in conditions:
        if budget_frees_at is None:
            return None
        instants.append(budget_frees_at)
    return max(instants) if instants else None


class DefaultNotificationPolicy:
    """ADR-0130 §5's five conditions, in the order §5 states them.

    The order below is normative:

    1. the four conditions of
       :data:`~ai_assistant.core.types.DROP_CONDITIONS`, each yielding ``DROP``
       naming itself;
    2. then the four of
       :data:`~ai_assistant.core.types.INTERRUPT_CONDITIONS`, all of which must
       hold for ``INTERRUPT``, and the first failing one of which a ``HOLD``
       names while carrying the whole failed set.

    **Sensitivity is not a condition here** (§5): a ``DataTier.SECRET`` candidate
    is refused by :class:`~ai_assistant.core.types.NotificationCandidate`'s own
    validator and never reaches a ruling.

    **A producer's confidence, its summary and its choice of class are evidence,
    not authority** (§4). They are read; no clause of §5 is satisfied by a
    producer asserting that it should be. And no numeric priority or urgency
    score is weighed at all (§11): perishability is the whole of the escalation
    test, because it is the one criterion a producer can be wrong about in public.
    """

    def __init__(self, *, timezone: str | ZoneInfo = "UTC") -> None:
        """Build the policy over the zone its quiet windows are read in.

        Args:
            timezone: The IANA zone ``Settings.timezone`` holds, or a
                :class:`zoneinfo.ZoneInfo`. **The only configuration a ruling
                reads**, and a construction-time property rather than an argument
                because a caller free to vary it per call could move the user's
                night (ADR-0130 §6). It is the same value ADR-0008 §5 gives the
                temporal context and ADR-0093 §7b binds the calendar reader to;
                no second timezone source is introduced.

        Raises:
            ZoneInfoNotFoundError: If the named zone is unknown. ``Settings``
                refuses one at load (ADR-0008 §5), so a composition root reaching
                here has already been validated.
        """
        self._zone = ZoneInfo(timezone) if isinstance(timezone, str) else timezone

    async def rule(  # noqa: PLR0913 — §4's determinism needs every input the ruling reads to be an argument
        self,
        candidate: NotificationCandidate,
        *,
        notification_id: str,
        preferences: NotificationPreferences,
        now: datetime,
        duplicate: bool,
        at_cap: bool,
        budget_spent: int,
        budget_frees_at: datetime | None,
    ) -> NotificationDisposition:
        """Rule on one candidate; see the Protocol for the whole contract.

        Args:
            candidate: The proposal to rule on.
            notification_id: The record this ruling would produce or update.
            preferences: The standing settings in force.
            now: The ruling instant, tz-aware. Every comparison is made against
                this one value rather than a clock this object reads, which is
                half of what makes the ruling reproducible.
            duplicate: Whether an actionable record carries this key (§8).
            at_cap: Whether the store is at its cap of actionable records (§7).
            budget_spent: ``INTERRUPT`` rulings inside the budget window (§6).
            budget_frees_at: When that window next frees a unit, or ``None``.

        Returns:
            The ruling, naming the condition that decided it.
        """
        reach = preferences.reach_for(candidate.notification_class)
        dropped = {
            NotificationCondition.EXPIRED: (
                candidate.expires_at is not None and not candidate.is_perishable_at(now)
            ),
            NotificationCondition.REACH_OFF: reach is NotificationReach.OFF,
            NotificationCondition.DUPLICATE: duplicate,
            NotificationCondition.AT_CAP: at_cap,
        }
        for condition in DROP_CONDITIONS:
            if dropped[condition]:
                return NotificationDisposition(
                    kind=NotificationDispositionKind.DROP,
                    notification_id=notification_id,
                    notification_class=candidate.notification_class,
                    ruled_at=now,
                    reason=condition,
                )

        quiet, quiet_until = self._quiet(now, preferences)
        held = {
            NotificationCondition.PERISHABLE: candidate.is_perishable_at(now),
            NotificationCondition.REACH_INTERRUPT: reach is NotificationReach.INTERRUPT,
            NotificationCondition.QUIET_WINDOW: not quiet,
            NotificationCondition.BUDGET: budget_spent < preferences.interruption_budget,
        }
        failed = tuple(condition for condition in INTERRUPT_CONDITIONS if not held[condition])
        if not failed:
            return NotificationDisposition(
                kind=NotificationDispositionKind.INTERRUPT,
                notification_id=notification_id,
                notification_class=candidate.notification_class,
                ruled_at=now,
                reason=NotificationCondition.PERISHABLE,
            )
        return NotificationDisposition(
            kind=NotificationDispositionKind.HOLD,
            notification_id=notification_id,
            notification_class=candidate.notification_class,
            ruled_at=now,
            reason=failed[0],
            failed=failed,
            reconsider_at=_next_due(
                failed, quiet_until=quiet_until, budget_frees_at=budget_frees_at
            ),
        )

    def _quiet(
        self, now: datetime, preferences: NotificationPreferences
    ) -> tuple[bool, datetime | None]:
        """Whether quiet covers ``now``, and when the covering stretch ends.

        **Answered in minute-of-day space rather than by chasing instants**, and
        that is what makes both hard cases right. A stretch of adjacent windows
        reads as one — a candidate is not released at a seam — however many
        windows it is made of. And a set of windows covering **every** minute of
        the day is recognised as such: quiet then never ends, so no instant
        resolves the condition and ``None`` is the honest answer, which §5 spells
        as a ``HOLD`` with no ``reconsider_at``. Returning a bounded future
        instant there would promise a re-ruling that can only re-hold, on every
        tick, for the life of the record.

        Args:
            now: The ruling instant, tz-aware.
            preferences: The settings holding the windows.

        Returns:
            Whether ``now`` is quiet, and the instant the quiet ends — ``None``
            both when nothing covers ``now`` and when nothing ever will not.
        """
        local = now.astimezone(self._zone)
        here = minute_of_day(local.time().replace(tzinfo=None))
        if not preferences.is_quiet_at(here):
            return False, None
        for step in range(1, MINUTES_IN_A_DAY):
            minute = (here + step) % MINUTES_IN_A_DAY
            if not preferences.is_quiet_at(minute):
                return True, self._instant_of(now, time(minute // 60, minute % 60))
        return True, None  # every minute of the day is quiet; time resolves nothing

    def _instant_of(self, now: datetime, end: time) -> datetime:
        """The first instant **strictly after** ``now`` at which the clock reads ``end``.

        Stated over instants rather than over dates, because a wall-clock time is
        not a function of the day it falls on and both transitions prove it.

        **The autumn fall-back repeats an hour, and the earlier reading is already
        spent**, so handing it back would make the record immediately due, re-rule
        it, recompute the same past instant, and spin the maintenance drain
        forever. Filtering to instants after ``now`` picks the reading the user's
        clock will actually reach next. **Where both readings are still ahead, the
        earlier wins**, which is ADR-0093 §7b's ``fold=0`` rule reached by taking
        the minimum rather than by naming a fold. **The spring transition skips a
        local time entirely**, and then the instant the clock next passes it is
        the transition itself: §5 asks for "the earliest instant at which every
        condition that failed could next hold".

        **Coverage stays a wall-clock question and is deliberately not
        fold-aware.** A user who sets quiet from 01:30 to 01:45 is speaking about
        what their clock reads, and on the night the hour repeats it reads that
        twice.

        Args:
            now: The ruling instant, tz-aware.
            end: The local time-of-day to reach, naive.

        Returns:
            The first instant after ``now`` whose local time-of-day is ``end``,
            in UTC.
        """
        here = now.astimezone(self._zone).date()
        reachable: list[datetime] = []
        for offset in (-1, 0, 1):
            nominal = datetime.combine(here + timedelta(days=offset), end, tzinfo=self._zone)
            existing = [
                moment
                for fold in (0, 1)
                if (moment := nominal.replace(fold=fold).astimezone(UTC))
                .astimezone(self._zone)
                .time()
                == end
            ]
            reachable.extend(
                existing
                or [
                    self._transition_between(
                        nominal.replace(fold=1).astimezone(UTC), nominal.astimezone(UTC)
                    )
                ]
            )
        return min(moment for moment in reachable if moment > now)

    def _transition_between(self, before: datetime, after: datetime) -> datetime:
        """The instant the offset changes, somewhere in ``(before, after]``.

        Found by bisection rather than read off the zone, ``zoneinfo`` publishing
        no transition table. The bracket is the two ``fold`` readings of a local
        time inside the gap, which straddle the transition by construction: the
        earlier reading still carries the old offset and the later one already
        carries the new.

        Args:
            before: An instant at the old offset.
            after: An instant at the new one.

        Returns:
            The first instant carrying the new offset, in UTC.
        """
        old = before.astimezone(self._zone).utcoffset()
        while after - before > timedelta(seconds=1):
            middle = before + (after - before) / 2
            if middle.astimezone(self._zone).utcoffset() == old:
                before = middle
            else:
                after = middle
        return after
