"""Local times, the person's zone, and a rule's arithmetic, for scheduled tasks (ADR-0340).

**Local times** (§3:2-§3:4). A spawn may state a local date and time with no UTC offset,
read in the zone it names or in the person's zone, and resolved to an instant when the
task is written. :func:`local_instant` is that reading: a local time a daylight-saving
change skips resolves to the first instant after the gap, and one it repeats to the
earlier of the two (``fold=0``).

**The person's zone** (§3:3, ADR-0338 §3:6). :class:`PersonZones` reads it for the person
a task is for, through :func:`~ai_assistant.orchestration.person_block.person_zone`, the one
function that reads a profile's zone, and holds the hub's ``Settings.timezone`` for where
the profile sets none. Every scheduled task's times are read and rendered in it (§6:1),
and a rule naming a zone in that zone instead (:func:`task_zone`).

**A rule's arithmetic** (§4:5-§4:8, §9:5) is :func:`next_occurrence`, the one function
every caller uses: the first instant a rule yields on or after a local date, later than an
instant. A rule's first occurrence (:func:`first_occurrence`), its successor
(:func:`successor`) and what the sensor states when it first pushes one, the latest missed
included (:func:`rule_push`), are each that function, read in the zone the rule is
computed in then. The plan store computes no instant: it writes what this module gives.

**The rule in words** (§6:2, §7:1, §8:2): :func:`rule_text`, which the read-back, the list
pull and an occurrence's input share.

It logs stage and code-owned reason only (ADR-0275 §8).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

from ai_assistant.core.errors import PersonModelStoreError
from ai_assistant.core.types import DueOnRule, RuleDay, RulePush, TaskRuleKind
from ai_assistant.orchestration.person_block import person_zone

if TYPE_CHECKING:
    from ai_assistant.core.protocols import PersonModelStore
    from ai_assistant.core.types import ScheduledTask

__all__ = [
    "PersonZones",
    "clock_text",
    "day_text",
    "first_occurrence",
    "local_instant",
    "next_occurrence",
    "resolve_zone",
    "rule_push",
    "rule_text",
    "successor",
    "task_zone",
]

_log = structlog.get_logger(__name__)

#: How far past its first candidate date a rule is looked at: a week holds every day a
#: version 1 rule can fall on (§4:2), and one more covers a candidate today already past.
_WEEK_AND_A_DAY: Final = 8

#: A rule's days, in the order of the week, as ``date.weekday()`` counts them.
_WEEK: Final = tuple(RuleDay)


def resolve_zone(name: str) -> ZoneInfo | None:
    """The zone an IANA name names, or ``None`` where ``zoneinfo`` does not resolve it.

    A spawn naming one that does not resolve is refused (§3:5).
    """
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError, ValueError:
        return None


def local_instant(local: datetime, zone: ZoneInfo) -> datetime:
    """A local date and time with no offset, read in ``zone``, as an instant in UTC (§3:4).

    A local time that exists once is that instant. One a daylight-saving change repeats
    is the earlier of the two (``fold=0``). One it skips, which no clock in ``zone``
    shows, is the first instant after the gap: the instant of the change itself.

    Args:
        local: The local date and time, naive.
        zone: The zone it is read in.

    Returns:
        The instant, in UTC.
    """
    wall = local.replace(tzinfo=None, fold=0)
    first = wall.replace(tzinfo=zone).astimezone(UTC)
    if first.astimezone(zone).replace(tzinfo=None) == wall:
        return first
    # A gap. ``fold=0`` reads it with the offset before the change, which lands after
    # the change; ``fold=1`` with the offset after it, which lands before. The change is
    # the first instant between them whose offset is no longer the earlier one.
    low = wall.replace(tzinfo=zone, fold=1).astimezone(UTC)
    high = first
    offset = low.astimezone(zone).utcoffset()
    while high - low > timedelta(seconds=1):
        middle = (low + (high - low) / 2).replace(microsecond=0)
        if middle.astimezone(zone).utcoffset() == offset:
            low = middle
        else:
            high = middle
    return high


def _falls_on(rule: DueOnRule, day: date) -> bool:
    """Whether ``rule`` yields an occurrence on the local date ``day`` (§4:2)."""
    if rule.repeats is TaskRuleKind.DAILY:
        return True
    if rule.repeats is TaskRuleKind.WEEKDAYS:
        return day.weekday() < _WEEK.index(RuleDay.SATURDAY)
    return _WEEK[day.weekday()] in rule.days


def next_occurrence(
    rule: DueOnRule,
    zone: ZoneInfo,
    *,
    on_or_after: date,
    later_than: datetime | None = None,
) -> datetime | None:
    """The first instant ``rule`` yields on or after a local date, in ``zone`` (§9:5).

    The one computation of a rule's instants. Each candidate is a local date the rule
    falls on, no earlier than its from (§4:4), at its local time of day read in ``zone``
    as :func:`local_instant` reads a local time (§4:9); the first later than
    ``later_than``, where it is given, is the answer.

    Args:
        rule: The rule.
        zone: The zone the rule is computed in now: its own, or the person's (§4:3).
        on_or_after: The first local date a candidate may fall on.
        later_than: An instant the answer must be later than, or ``None``.

    Returns:
        The instant, in UTC; ``None`` where the next candidate would fall after the
        rule's until (§4:7).
    """
    day = on_or_after if rule.from_date is None else max(on_or_after, rule.from_date)
    for _ in range(_WEEK_AND_A_DAY):
        if rule.until_date is not None and day > rule.until_date:
            return None
        if _falls_on(rule, day):
            instant = local_instant(datetime.combine(day, rule.time_of_day), zone)
            if later_than is None or instant > later_than:
                return instant
        try:
            day += timedelta(days=1)
        except OverflowError:
            return None
    return None


def first_occurrence(rule: DueOnRule, zone: ZoneInfo, *, now: datetime) -> datetime | None:
    """A rule's first occurrence: the first instant it yields later than now (§4:5).

    On or after its from, read in ``zone``; ``None`` where it yields none later than now
    before its until, which the spawn refuses (§4:4).
    """
    return next_occurrence(rule, zone, on_or_after=now.astimezone(zone).date(), later_than=now)


def successor(rule: DueOnRule, due_at: datetime, zone: ZoneInfo) -> datetime | None:
    """The successor of an occurrence due at ``due_at`` (§4:6).

    The first instant the rule yields on a local date later than ``due_at``'s own, both
    read in ``zone``, so no local day holds two occurrences; ``None`` where it would fall
    after the rule's until.
    """
    own = due_at.astimezone(zone).date()
    try:
        after = own + timedelta(days=1)
    except OverflowError:
        return None
    return next_occurrence(rule, zone, on_or_after=after)


def rule_push(rule: DueOnRule, due_at: datetime, zone: ZoneInfo, *, now: datetime) -> RulePush:
    """What the sensor states when it first pushes a rule's pending occurrence (§4:6, §4:8).

    The pending occurrence keeps its stored instant, ``due_at``, unchanged. Its
    successors are computed in turn, in ``zone``, up to ``now``: where none is due by
    then, the pending occurrence is the one pushed; where any is, the rule missed more
    than one, and the latest of them is pushed in its place, the pending one and each
    other earlier one recorded *skipped*. Either way, the one pushed is followed by its
    own successor, or by none where the rule has ended.

    Args:
        rule: The rule.
        due_at: The pending occurrence's instant, as stored.
        zone: The zone the rule is computed in now.
        now: The instant of the push.

    Returns:
        The instants the plan store writes in the push's step.
    """
    missed: list[datetime] = []
    following = successor(rule, due_at, zone)
    while following is not None and following <= now:
        missed.append(following)
        following = successor(rule, following, zone)
    if not missed:
        return RulePush(successor=following)
    return RulePush(successor=following, skipped=tuple(missed[:-1]), latest=missed[-1])


class PersonZones:
    """The person's zone, read for the person a task is for (§3:3, ADR-0338 §3:6)."""

    def __init__(self, *, default: ZoneInfo, people: PersonModelStore | None = None) -> None:
        """Wire the reading.

        Args:
            default: ``Settings.timezone``, the zone where a profile sets none.
            people: The person-model store, or ``None`` where the person model is off,
                so no profile is read and ``default`` governs.
        """
        self._default = default
        self._people = people

    @property
    def default(self) -> ZoneInfo:
        """``Settings.timezone``'s zone."""
        return self._default

    async def of(self, person: str) -> ZoneInfo:
        """``person``'s zone: their profile's where it sets one, and the hub's otherwise.

        A store that cannot be read is logged, and the hub's zone governs, as it does for
        planning's current time where the person block could not be read (ADR-0338 §3:6,
        §7:1): so a local time planning stated from the time it was shown is read in the
        zone it was shown in.
        """
        if self._people is None:
            return self._default
        try:
            model = await self._people.read(person)
        except PersonModelStoreError:
            _log.warning("task_zone_unread", stage="task_scheduler", reason="store_fault")
            return self._default
        zone = person_zone(None if model is None else model.profile, stage="task_scheduler")
        return self._default if zone is None else zone


def task_zone(task: ScheduledTask, person: ZoneInfo) -> ZoneInfo:
    """The zone ``task``'s times are computed and rendered in (§4:3, §6:1).

    A rule naming a zone, in that zone; every other task, and a rule naming none, in the
    person's. A stored zone this host's tz database no longer resolves is logged, and the
    person's zone is used: the record is kept as written (ADR-0340 §9:1).
    """
    when = task.when
    if not isinstance(when, DueOnRule) or when.zone is None:
        return person
    named = resolve_zone(when.zone)
    if named is None:
        _log.warning("task_zone_unresolved", stage="task_scheduler", reason="rule_zone")
        return person
    return named


def clock_text(at: time) -> str:
    """A local time of day as the hub says it back: ``8:00 PM``."""
    hour = at.hour % 12 or 12
    return f"{hour}:{at.minute:02d} {'AM' if at.hour < 12 else 'PM'}"  # noqa: PLR2004 — noon


def day_text(day: date, *, today: date) -> str:
    """A local date as the hub says it back, ``Thursday 23 October``, its year if not today's."""
    year = "" if day.year == today.year else f" {day.year}"
    return f"{day:%A} {day.day} {day:%B}{year}"


def _days_text(days: tuple[RuleDay, ...]) -> str:
    named = [one.value.capitalize() for one in days]
    if len(named) == 1:
        return named[0]
    return f"{', '.join(named[:-1])} and {named[-1]}"


def rule_text(rule: DueOnRule, *, today: date) -> str:
    """A rule in words, with its zone where it names one, and its from and until (§6:2).

    Such as ``every weekday at 7:00 AM, until Friday 31 October``. A from on or before
    ``today`` constrains nothing (§4:4), so it is not said.

    Args:
        rule: The rule.
        today: The local date it is said on, in the zone it is rendered in.
    """
    if rule.repeats is TaskRuleKind.WEEKLY:
        repeats = f"every {_days_text(rule.days)}"
    elif rule.repeats is TaskRuleKind.WEEKDAYS:
        repeats = "every weekday"
    else:
        repeats = "every day"
    said = f"{repeats} at {clock_text(rule.time_of_day)}"
    if rule.zone is not None:
        said += f" {rule.zone} time"
    if rule.from_date is not None and rule.from_date > today:
        said += f", from {day_text(rule.from_date, today=today)}"
    if rule.until_date is not None:
        said += f", until {day_text(rule.until_date, today=today)}"
    return said
