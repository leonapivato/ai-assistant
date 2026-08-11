"""Canonical fakes for the three notification Protocols (ADR-0130 §9).

The shared test doubles for :class:`~ai_assistant.core.protocols.NotificationPolicy`,
:class:`~ai_assistant.core.protocols.NotificationWriter` and
:class:`~ai_assistant.core.protocols.NotificationStore`, so a subsystem that
depends on proactive contact can test against a real, contract-correct trio
*without importing another subsystem's internals* (CLAUDE.md golden rule 1).

**The policy fake is not a stub, and it cannot be.** ADR-0130 §4 makes the
disposition mechanical and §5 states it as five conditions in a fixed order, so
"a fake that returns whatever the test wants" would be a fake of a *model* —
which is exactly what §11 forbids the real thing from being. There is nothing
here for a stub to stand in for: the ruling is a pure function of the candidate,
the standing preferences, the store's four facts and the instant, and
:class:`FakeNotificationPolicy` is that function.

**The store's critical sections really suspend.** Every ruling operation yields
to the event loop inside its exclusion, before reading the state it is about to
change. Without that, a fake backed by a dict would satisfy §3's atomicity
clause by accident — nothing in it ever awaits, so nothing can interleave — and
the shared suite's concurrency cases would be vacuous against exactly the
implementation they most need to hold for.

**The store defaults to ADR-0130's own figures**, not to whatever was convenient:
a cap of 100 actionable records and a retention of seven days. A fake looser than
the contract would certify consumers a real store rejects.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time, timedelta
from itertools import count
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import NotificationStoreError
from ai_assistant.core.types import (
    DROP_CONDITIONS,
    INTERRUPT_CONDITIONS,
    MINUTES_IN_A_DAY,
    TIME_RESOLVED_CONDITIONS,
    HeldNotification,
    NotificationCondition,
    NotificationDisposition,
    NotificationDispositionKind,
    NotificationPreferences,
    NotificationReach,
    describe_untrusted,
    minute_of_day,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import NotificationPolicy, NotificationStore
    from ai_assistant.core.types import NotificationCandidate

#: One past the largest value a paging argument accepts — the signed 64-bit
#: ceiling a SQLite bind parameter tops out at (ADR-0073 §2). Duplicated rather
#: than shared for ``FakeDeferralStore``'s reason: ``ai_assistant.testing`` may
#: not import a subsystem (golden rule 1).
_PAGE_BOUND = 2**63

#: The most actionable records the store holds (ADR-0130 §7). Strictly positive
#: with no "unlimited" spelling: a cap of zero is at capacity before its first
#: admission.
_DEFAULT_CAP = 100

#: How long a record is kept after it ceases to be actionable (ADR-0130 §7).
#: **Finite**, and deliberately shorter than the deferral queue's thirty days: a
#: question keeps its value until it is answered, a notification about a thing
#: that already happened does not.
_DEFAULT_RETENTION = timedelta(days=7)

#: The bounded default every enumeration here uses (ADR-0073 §2, §8).
_DEFAULT_PAGE_LIMIT = 50


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _check_page_bound(name: str, value: object, *, floor: int = 0) -> None:
    """Refuse a paging argument that is not an exact ``int`` in ``[floor, 2**63)``.

    **The type is part of the range**: without it this fake would slice a list on
    ``limit=1.5`` where a real store raises out of its driver, and two stores
    disagreeing about a bad argument is the failure ADR-0073 §2 exists to stop.
    ``bool`` is refused with the rest, being an ``int`` subclass that is not a
    page size.

    Args:
        name: The argument's name, for the message.
        value: What the caller supplied.
        floor: The smallest admissible value.

    Raises:
        ValueError: If ``value`` is not an ``int``, is below ``floor``, or is
            beyond the signed 64-bit range.
    """
    if type(value) is not int or not floor <= value < _PAGE_BOUND:
        msg = f"{name} must be an int in [{floor}, 2**63), got {describe_untrusted(value)}"
        raise ValueError(msg)


class FakeNotificationPolicy:
    """The deterministic ruling of ADR-0130 §5, as a canonical fake.

    **No model is consulted and none may be** (§11). Every answer is a function
    of the arguments and of this object's one construction-time property, the
    timezone quiet windows are read in — so the same inputs return the same
    disposition however often it is asked, which is §4's obligation rather than a
    coincidence of the implementation.

    The order below is normative and is the order §5 states:

    1. the four conditions of
       :data:`~ai_assistant.core.types.DROP_CONDITIONS`, each yielding ``DROP``
       naming itself;
    2. then the four of
       :data:`~ai_assistant.core.types.INTERRUPT_CONDITIONS`, all of which must
       hold for ``INTERRUPT``, and the first failing one of which a ``HOLD``
       names while carrying the whole failed set.

    **Sensitivity is not a condition here** (§5): a ``DataTier.SECRET``
    candidate is refused by
    :class:`~ai_assistant.core.types.NotificationCandidate`'s own validator and
    never reaches a ruling.
    """

    def __init__(self, *, timezone: str | ZoneInfo = "UTC") -> None:
        """Build the policy over the zone its quiet windows are read in.

        Args:
            timezone: The IANA zone ``Settings.timezone`` holds, or a
                :class:`zoneinfo.ZoneInfo`. **The only configuration a ruling
                reads**, and a construction-time property rather than an
                argument because a caller free to vary it per call could move
                the user's night (ADR-0130 §6).
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
            now: The ruling instant, tz-aware.
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
        windows it is made of, where a bounded chase silently shortened the answer
        past its cap. And a set of windows covering **every** minute of the day is
        recognised as such: quiet then never ends, so no instant resolves the
        condition and ``None`` is the honest answer, which §5 spells as a ``HOLD``
        with no ``reconsider_at``. Returning a bounded future instant there would
        promise a re-ruling that can only re-hold, on every tick, for the life of
        the record.

        The day is a cycle of ``MINUTES_IN_A_DAY`` minutes, so walking it once
        settles both: the first uncovered minute at or after the current one is
        the answer, and its absence *is* the all-day case.

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

        **The autumn fall-back repeats an hour, and the earlier reading is
        already spent.** At 01:35 EST on 2026-11-01 — the *second* 01:35 — the
        ``fold=0`` reading of 01:45 is 05:45Z, fifty minutes in the past. Handing
        that back as a due instant made the record immediately due, so a
        reconsideration re-ruled it, recomputed the same past instant, and the
        maintenance drain ran forever. Filtering to instants after ``now`` picks
        06:45Z, the second 01:45, which is what the user's clock will actually
        read next.

        **Where both readings are still ahead, the earlier wins**, which is
        ADR-0093 §7b's ``fold=0`` rule reached by taking the minimum rather than
        by naming a fold.

        **The spring transition skips a local time entirely**, and then neither
        reading round-trips; the instant the clock next passes it is the
        transition itself (:meth:`_transition_between`). §5 asks for "the earliest
        instant at which every condition that failed could next hold", so that is
        the one to name.

        **Coverage stays a wall-clock question and is deliberately not
        fold-aware.** A user who sets quiet from 01:30 to 01:45 is speaking about
        what their clock reads, and on the night the hour repeats it reads that
        twice; quieting both is the reading that matches what they asked for.

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


class FakeNotificationStore:
    """A dict-backed :class:`~ai_assistant.core.protocols.NotificationStore`.

    One dict of records, one held preferences value, an injected clock and an
    injected id source. It honours the whole contract, including the parts a
    dict gets for free only if they are written down: the atomicity of a ruling,
    the cap counting the actionable set, the duplicate rule reading that same
    set, the retention anchored on cessation rather than on admission, and §6's
    two setting-change sweeps.
    """

    def __init__(
        self,
        *,
        now: Callable[[], datetime] = _utcnow,
        retention: timedelta | None = _DEFAULT_RETENTION,
        cap: int = _DEFAULT_CAP,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        """Build the store over its injected seams, refusing unusable tuning.

        Args:
            now: The clock, wrapped by
                :func:`~ai_assistant.core.clock.checked_clock` exactly as a real
                store wraps it.
            retention: How long a record is kept after it ceases to be
                actionable, stamped onto each record at admission. ``None``
                means never purged.
            cap: The most actionable records this store holds.
            new_id: The record-id source; a counter by default, this being an
                identity rather than a capability.

        Raises:
            ValueError: If ``cap`` is not an exact ``int`` in ``(0, 2**63)``, or
                ``retention`` is a duration that is not strictly positive.
        """
        if type(cap) is not int or not 0 < cap < _PAGE_BOUND:
            msg = (
                f"cap must be an int in (0, 2**63), got {describe_untrusted(cap)}: a cap of "
                f"0 is at capacity before its first admission (ADR-0130 §7)"
            )
            raise ValueError(msg)
        if retention is not None and (
            not isinstance(retention, timedelta) or retention <= timedelta(0)
        ):
            msg = (
                f"retention must be a strictly positive duration or None, got "
                f"{describe_untrusted(retention)}"
            )
            raise ValueError(msg)
        self._clock: Clock = checked_clock(now, owner="FakeNotificationStore")
        self._retention = retention
        self._cap = cap
        self._counter = count(1)
        self._new_id = new_id or (lambda: f"ntf-{next(self._counter)}")
        self._records: dict[str, HeldNotification] = {}
        #: When each ``INTERRUPT`` disposition was **recorded** (ADR-0130 §5), kept
        #: apart from the records themselves so that destroying a notification does
        #: not refund the unit it spent. See :meth:`_budget`.
        self._spent: list[datetime] = []
        self._preferences = NotificationPreferences()
        self._lock = asyncio.Lock()

    @property
    def cap(self) -> int:
        """The most actionable records this store holds (ADR-0130 §7)."""
        return self._cap

    def _now(self) -> datetime:
        """Read the clock, reporting an unusable reading as this store's error.

        Returns:
            The reading, aware and UTC.

        Raises:
            NotificationStoreError: If the clock's reading is unusable.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            msg = "the notification store's clock returned an unusable reading"
            raise NotificationStoreError(msg) from exc

    async def admit(
        self, candidate: NotificationCandidate, *, policy: NotificationPolicy
    ) -> NotificationDisposition:
        """Rule on an offered candidate and record the ruling atomically (§3).

        Args:
            candidate: What was noticed.
            policy: The ruling, asked inside the critical section.

        Returns:
            The disposition, carrying no ``notification_id`` where it is a
            ``DROP`` — §8 wrote no record for one.
        """
        async with self._lock:
            await asyncio.sleep(0)  # the suspension a real store's I/O has anyway
            now = self._now()
            record_id = self._fresh_id()
            spent, frees_at = self._budget(now)
            ruling = await policy.rule(
                candidate,
                notification_id=record_id,
                preferences=self._preferences,
                now=now,
                duplicate=self._is_duplicate(candidate.candidate_key, now),
                at_cap=len(self._actionable(now)) >= self._cap,
                budget_spent=spent,
                budget_frees_at=frees_at,
            )
            if ruling.kind is NotificationDispositionKind.DROP:
                return ruling.model_copy(update={"notification_id": None})
            # Built before anything is committed: a record the type refuses must
            # leave no spent unit behind it (ADR-0130 §5).
            record = HeldNotification(
                id=record_id,
                candidate=candidate,
                kind=ruling.kind,
                reason=ruling.reason,
                failed=ruling.failed,
                ruled_at=now,
                reconsider_at=ruling.reconsider_at,
                admitted_at=now,
                retention=self._retention,
            )
            self._record_spend(ruling)
            self._records[record_id] = record
            return ruling

    async def reconsider(
        self, notification_id: str, *, policy: NotificationPolicy
    ) -> NotificationDisposition | None:
        """Re-rule one due record in place, atomically (§5).

        Args:
            notification_id: The record to re-rule.
            policy: The ruling, asked inside the critical section.

        Returns:
            The fresh disposition, or ``None`` where nothing was due under that
            id.
        """
        async with self._lock:
            await asyncio.sleep(0)
            now = self._now()
            record = self._records.get(notification_id)
            if record is None or not record.is_due_at(now):
                return None
            spent, frees_at = self._budget(now)
            ruling = await policy.rule(
                record.candidate,
                notification_id=record.id,
                preferences=self._preferences,
                now=now,
                # A reconsideration is not an offer: it never matches itself
                # (§5), and the record already holds its slot under the cap.
                duplicate=False,
                at_cap=False,
                budget_spent=spent,
                budget_frees_at=frees_at,
            )
            ruled = HeldNotification(
                id=record.id,
                candidate=record.candidate,
                kind=ruling.kind,
                reason=ruling.reason,
                failed=ruling.failed,
                ruled_at=now,
                reconsider_at=ruling.reconsider_at,
                admitted_at=record.admitted_at,
                retention=record.retention,
                dismissed_at=record.dismissed_at,
                dropped_at=now if ruling.kind is NotificationDispositionKind.DROP else None,
            )
            self._record_spend(ruling)
            self._records[record.id] = ruled
            return ruling

    async def due(
        self, *, limit: int = _DEFAULT_PAGE_LIMIT, offset: int = 0
    ) -> list[HeldNotification]:
        """The records whose ``reconsider_at`` has arrived, oldest due first.

        Args:
            limit: How many to return.
            offset: How many to skip.

        Returns:
            A detached snapshot.

        Raises:
            ValueError: If a paging argument is outside ``[0, 2**63)``.
        """
        _check_page_bound("limit", limit)
        _check_page_bound("offset", offset)
        now = self._now()
        ordered = sorted(
            (record for record in self._records.values() if record.is_due_at(now)),
            key=lambda record: (record.reconsider_at or now, record.id),
        )
        return ordered[offset : offset + limit]

    async def held(
        self, *, limit: int = _DEFAULT_PAGE_LIMIT, offset: int = 0
    ) -> list[HeldNotification]:
        """Every retained record, oldest first (§7).

        Args:
            limit: How many to return.
            offset: How many to skip.

        Returns:
            A detached snapshot.

        Raises:
            ValueError: If a paging argument is outside ``[0, 2**63)``.
        """
        _check_page_bound("limit", limit)
        _check_page_bound("offset", offset)
        return self._ordered()[offset : offset + limit]

    async def get(self, notification_id: str) -> HeldNotification | None:
        """One record by id, or ``None``.

        Args:
            notification_id: The record to read.

        Returns:
            The record, or ``None`` where the id names nothing.
        """
        return self._records.get(notification_id)

    async def dismiss(self, notification_id: str) -> bool:
        """End one record's actionability, leaving it readable (§7).

        Args:
            notification_id: The record to dismiss.

        Returns:
            Whether an actionable record was dismissed.
        """
        async with self._lock:
            await asyncio.sleep(0)
            now = self._now()
            record = self._records.get(notification_id)
            if record is None or not record.is_actionable_at(now):
                return False
            self._records[record.id] = record.model_copy(update={"dismissed_at": now})
            return True

    async def preferences(self) -> NotificationPreferences:
        """The standing settings in force, defaulted where nothing is set (§6).

        Returns:
            The settings.
        """
        return self._preferences

    async def set_preferences(self, preferences: NotificationPreferences) -> int:
        """Write the settings and re-arm what the change reaches (§6).

        Args:
            preferences: The settings to hold from now on.

        Returns:
            How many records the write made due for reconsideration.
        """
        async with self._lock:
            await asyncio.sleep(0)
            now = self._now()
            previous = self._preferences
            removable = _conditions_a_change_removes(previous, preferences)
            raised = _classes_reaching(previous, preferences, NotificationReach.INTERRUPT)
            silenced = _classes_reaching(previous, preferences, NotificationReach.OFF)
            touched = 0
            for record in list(self._records.values()):
                if record.kind is not NotificationDispositionKind.HOLD:
                    continue  # no setting change reaches a record already ruled INTERRUPT
                if not record.is_actionable_at(now):
                    continue
                held_class = record.candidate.notification_class
                reaches = (
                    held_class in silenced
                    or (
                        held_class in raised
                        and NotificationCondition.REACH_INTERRUPT in record.failed
                    )
                    or bool(set(record.failed) & removable)
                )
                if reaches:
                    self._records[record.id] = record.model_copy(update={"reconsider_at": now})
                    touched += 1
            self._preferences = preferences
            return touched

    async def delete(self, notification_id: str) -> bool:
        """Destroy one record unconditionally (§9).

        Args:
            notification_id: The record to destroy.

        Returns:
            Whether a record was removed.
        """
        return self._records.pop(notification_id, None) is not None

    async def clear(self) -> int:
        """Destroy every record, leaving the standing settings alone (§9).

        Returns:
            How many records were destroyed.
        """
        removed = len(self._records)
        self._records.clear()
        return removed

    async def export(self) -> list[HeldNotification]:
        """Every stored record, for the user's own data export (ADR-0004 §6).

        Returns:
            The records, oldest first.
        """
        return self._ordered()

    async def purge(self) -> int:
        """Sweep the records retention has released (§7).

        Returns:
            How many records were removed.
        """
        now = self._now()
        doomed = [record.id for record in self._records.values() if record.is_purgeable_at(now)]
        for record_id in doomed:
            del self._records[record_id]
        return len(doomed)

    # --- the store's own bookkeeping ---------------------------------------

    def _ordered(self) -> list[HeldNotification]:
        """Every record, oldest first, on ADR-0078 §7's ordering.

        Returns:
            The records by ``admitted_at`` then ``id``.
        """
        return sorted(self._records.values(), key=lambda record: (record.admitted_at, record.id))

    def _actionable(self, now: datetime) -> list[HeldNotification]:
        """The population the cap counts and §8's duplicate rule reads (§7).

        Args:
            now: The instant to judge at.

        Returns:
            The actionable records.
        """
        return [record for record in self._records.values() if record.is_actionable_at(now)]

    def _is_duplicate(self, candidate_key: str, now: datetime) -> bool:
        """Whether an actionable record already carries this key (§8).

        Args:
            candidate_key: The offered candidate's key.
            now: The instant to judge actionability at.

        Returns:
            Whether the key is already spoken for.
        """
        return any(
            record.candidate.candidate_key == candidate_key for record in self._actionable(now)
        )

    def _fresh_id(self) -> str:
        """Draw a record id, refusing one this store already holds.

        **A store that overwrote a record here would lose one silently**, and the
        two dispositions would name the same id — which is `DeferralStore.defer`'s
        argument for making a present id "a hard error, not an overwrite" rather
        than letting "a dict-backed store silently overwrite someone else's
        pending question while a SQL one raises".

        A collision is the *store's* fault and never a caller's: ids are minted
        here and no caller supplies one, so this is a store fault and carries the
        store's error rather than a ``ValueError``.

        Returns:
            An id no record holds.

        Raises:
            NotificationStoreError: If the id source returns something blank or
                already present.
        """
        record_id = self._new_id()
        if not isinstance(record_id, str) or not record_id.strip():
            msg = (
                f"the notification store's id source returned "
                f"{describe_untrusted(record_id)}, which is not an identifier"
            )
            raise NotificationStoreError(msg)
        if record_id in self._records:
            msg = (
                f"the notification store's id source returned {record_id!r}, which a "
                f"stored record already holds: admitting over it would lose that record "
                f"and leave two dispositions naming one id"
            )
            raise NotificationStoreError(msg)
        return record_id

    def _record_spend(self, ruling: NotificationDisposition) -> None:
        """Note a unit spent, if this ruling spent one (ADR-0130 §5).

        A unit is spent when an ``INTERRUPT`` disposition is **recorded**, never
        when contact is attempted and never when it succeeds — and a
        reconsideration ruled ``INTERRUPT`` spends one like any other ruling.

        Args:
            ruling: What was just decided.
        """
        if ruling.kind is NotificationDispositionKind.INTERRUPT:
            self._spent.append(ruling.ruled_at)

    def _budget(self, now: datetime) -> tuple[int, datetime | None]:
        """The two budget facts §5's conjunctive clause reads (§6).

        **The spend outlives the notification, and that is the whole reason it is
        kept apart from the records.** §5 is unconditional that "no spent unit is
        refunded except by an act that says so", and deriving the count from the
        retained records would have made three ordinary acts refund one silently:
        deleting a notification, clearing them all, and a retention purge running
        with a horizon shorter than the budget window. The last is not even a
        user's act — it is a scheduler's — so the budget would quietly widen on a
        timer, which is precisely the bound §5 exists to make computable.

        **What is kept is a bare instant.** No key, no summary, no class, nothing
        of the candidate: this is a rate limiter's state and not the user's
        content, so it is neither exported nor reached by ADR-0004 §6's delete
        right, and destroying a notification still destroys everything the
        notification said.

        **Widening the budget window does forget the older spends**, and that is
        the "act that says so" §5 leaves room for: the user asking to be
        interrupted more is the one party entitled to grant it. Entries outside
        the window in force are pruned here rather than accumulating, which is
        also what keeps this list bounded by the window rather than by uptime.

        Args:
            now: The ruling instant.

        Returns:
            How many units are spent inside the window, and when it next frees
            one — ``None`` where time alone will not.
        """
        preferences = self._preferences
        window = preferences.budget_window
        self._spent = sorted(at for at in self._spent if at > now - window)
        budget = preferences.interruption_budget
        frees_at: datetime | None = None
        if budget > 0 and len(self._spent) >= budget:
            frees_at = self._spent[len(self._spent) - budget] + window
        return len(self._spent), frees_at


def _classes_reaching(
    previous: NotificationPreferences,
    current: NotificationPreferences,
    reach: NotificationReach,
) -> frozenset[str]:
    """The classes the write moved *to* ``reach`` from something else.

    Args:
        previous: The settings before the write.
        current: The settings after it.
        reach: The level to look for.

    Returns:
        The class names whose reach changed to ``reach``.
    """
    named = {row.notification_class for row in previous.reaches} | {
        row.notification_class for row in current.reaches
    }
    return frozenset(
        name
        for name in named
        if current.reach_for(name) is reach and previous.reach_for(name) is not reach
    )


def _conditions_a_change_removes(
    previous: NotificationPreferences, current: NotificationPreferences
) -> frozenset[NotificationCondition]:
    """The failed conditions this write could remove, other than the reach one.

    §6 stamps a due instant onto every actionable held record whose *failed set*
    holds a condition the change could remove — the whole set, never the first
    reason alone, which is what buys the user the hours they just paid for when
    a record failed two conditions and the change removed the second.

    Args:
        previous: The settings before the write.
        current: The settings after it.

    Returns:
        The conditions to look for in a record's failed set.
    """
    removable: set[NotificationCondition] = set()
    if previous.quiet_windows != current.quiet_windows:
        removable.add(NotificationCondition.QUIET_WINDOW)
    if (previous.interruption_budget, previous.budget_window) != (
        current.interruption_budget,
        current.budget_window,
    ):
        removable.add(NotificationCondition.BUDGET)
    return frozenset(removable)


class FakeNotificationWriter:
    """The single seam of ADR-0130 §3, over a store and a policy.

    Deliberately thin, and that thinness is the contract's shape rather than the
    fake's shortcut: §3 requires the duplicate lookup, the cap check, the budget
    read, the ruling and the write to be **one atomic act in the store**, so the
    seam's job is to hold the policy and hand it to the store, never to sequence
    those steps itself. A writer that read the state, ruled, and then wrote would
    satisfy every word of §3 except the one that matters.
    """

    def __init__(self, *, store: NotificationStore, policy: NotificationPolicy) -> None:
        """Wire the seam to the store it writes through and the policy it asks.

        Args:
            store: Where records live and where the atomic act happens.
            policy: The deterministic ruling of §4 and §5.
        """
        self._store = store
        self._policy = policy

    @property
    def store(self) -> NotificationStore:
        """The store this seam writes through.

        Public on the fake so a conformance suite can read back what an offer
        recorded without reaching into a private attribute — the seam itself
        publishes nothing of the sort, and a real writer need not.
        """
        return self._store

    async def offer(self, candidate: NotificationCandidate) -> NotificationDisposition:
        """Offer one candidate and report what was ruled about it (§3).

        Args:
            candidate: What the producer noticed.

        Returns:
            The ruling, naming the condition that decided it.
        """
        return await self._store.admit(candidate, policy=self._policy)


__all__ = ["FakeNotificationPolicy", "FakeNotificationStore", "FakeNotificationWriter"]
