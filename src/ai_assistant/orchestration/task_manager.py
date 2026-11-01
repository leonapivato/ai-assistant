"""The Task Manager, and planning's three calls on the Task Scheduler (ADR-0350 §4, §9, §10).

**The Task Manager** (§10) is the one way in from outside for managing activations and
scheduled tasks: a surface of commands and queries the assistant does not perceive
(ADR-0292 §1:3), not a spoke on a channel. Its queries are what is running, live from the
engine; what is scheduled, from the Task Scheduler; and what ran lately, from the
schedule's episodes (§10:2). Its commands are the stop, which is the one stop
``AssistantEngine.stop_activation`` runs (§10:3) and stops only the activation it names
(ADR-0352 §2:1); cancel (§9:5); and replace (§9:4). No operation reaches the local API
(§10:6): the engine holds this object, and the hub chat's stop control and the line's
``/stop`` reach its stop through the engine's.

**Inside, the same operations serve** (§10:4): planning's list pull is its queries, and
planning's cancel and its spawn that replaces a task are its commands under §4:4's checks,
each with one implementation here. :class:`ScheduledTaskCalls` is acting's runner for the
three capabilities, over this one :class:`TaskManager`.

**What a stopped activation set up** (ADR-0352 §3:1-§3:6). No stop reaches below the
activation it names, so a stop call's result shows what is still live below it:
:meth:`TaskManager.still_live` reads, and changes nothing.

**What keeps the schedule tidy** (§7:8). A task is kept while anything of it or below it
is live, while a task the Task Scheduler holds waits on it, and while its parent still
runs; once none of these holds it is removed. The store decides all but the last, which
is the engine's state: :meth:`TaskManager.tidy` asks the store to remove a task only
where its parent is not running, and walks up from each task removed to the task above it
and to the tasks it waited on, which may now be removable in turn.

**The place list** (§5:10-§5:13). :class:`PlaceLists` builds an activation's list when it
is shown: the line's chat, where the line is connected, and, for an activation the Task
Scheduler started, its task's suggested places that are not gone, marked as suggested;
for every other activation, the conversation its input came from. A conversation is gone
once deleted, and the line's chat once the line is disconnected or the settings name
another chat (§5:8). Nothing is cancelled because a place is gone (§5:9).

**Tasks the person sets** (ADR-0340). A spawn may state a local date and time with no
offset, read in the zone it names or in the person's zone (§3:2-§3:4), or a rule, which
only a task the person set holds (§4); its refusals are each *not done*, with the reason
(§3:5, §4:4). Every rendering of a scheduled task's times, the queries' included, is in
the person's zone, read for the person each is for (§6:1), and a spawn's result carries
the read-back (§6:2).

**It logs stage and code-owned reason only** (ADR-0275 §8).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.errors import (
    ConversationStoreError,
    MemoryStoreError,
    PersonModelStoreError,
    PlanningError,
)
from ai_assistant.core.types import (
    ActivationEffect,
    ActivationEffectClaim,
    ChannelIdentity,
    DueAfterTasks,
    DueAt,
    DueNow,
    DueOnRule,
    EpisodicMemory,
    OccurrenceState,
    RuleDay,
    ScheduledTaskAuthor,
    TapOnCard,
    TaskRefusal,
    TaskRuleKind,
    TaskSpawn,
    TaskWriteAnswer,
    ToolOutcome,
    ToolResult,
    parties_are_assistants,
)
from ai_assistant.orchestration.acting import TICKET_CLAIM_TEXT, Unwritten
from ai_assistant.orchestration.channel_kinds import place_channel, place_of
from ai_assistant.orchestration.disclosure import admitted_to_understanding
from ai_assistant.orchestration.episode_reads import without_open_episodes
from ai_assistant.orchestration.matters import in_progress
from ai_assistant.orchestration.outside_content import holds_outside
from ai_assistant.orchestration.person_block import activation_person
from ai_assistant.orchestration.person_calls import NotDone
from ai_assistant.orchestration.task_rules import (
    PersonZones,
    first_occurrence,
    local_instant,
    resolve_zone,
    rule_text,
    task_zone,
)
from ai_assistant.orchestration.task_scheduler import (
    AFTER_ARGUMENT,
    AT_ARGUMENT,
    CANCEL_TASK_CAPABILITY,
    DAYS_PART,
    DELAY_ARGUMENT,
    FROM_PART,
    INSTRUCTION_ARGUMENT,
    LIST_TASKS_CAPABILITY,
    PLACES_ARGUMENT,
    REPEATS_PART,
    REPLACES_ARGUMENT,
    RULE_ARGUMENT,
    SCHEDULE,
    SPAWN_CAPABILITY,
    TASK_ARGUMENT,
    TIME_PART,
    UNTIL_PART,
    ZONE_ARGUMENT,
    ActivationEntry,
    ListedPlace,
    Spawner,
    StartingEntry,
    StillLive,
    TaskEntry,
    TaskListing,
    current_spawner,
    encode_listing,
    local_time,
    outcome_text,
    place_description,
    read_back,
    shown_occurrence,
    when_text,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Sequence
    from zoneinfo import ZoneInfo

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import ConversationStore, MemoryStore, PlanStore
    from ai_assistant.core.types import (
        FrozenJson,
        ProcessingReason,
        ProcessingStatus,
        ScheduledTask,
        ScheduledTaskCancel,
        ScheduledTaskWrite,
        TaskWhen,
        ToolCall,
    )
    from ai_assistant.orchestration.acting import ClaimingAnswer, OwnRecordsAnswer
    from ai_assistant.orchestration.activation_state import ActivationState
    from ai_assistant.orchestration.disclosure import TurnSupply

__all__ = [
    "PlaceLists",
    "ScheduledTaskCalls",
    "StatedWhen",
    "TaskManager",
    "TaskManagerLimits",
    "TaskParent",
    "TaskSchedulerSeams",
    "spawn_when",
]

_log = structlog.get_logger(__name__)

#: How much of a text the listing shows of it in brief.
_BRIEF_CHARS: Final = 160

#: The channel headings a place list groups its places under (§5:10).
_HUB_CHAT: Final = "The hub's chat"
_TELEGRAM: Final = "Telegram"

#: The code-owned reasons a call is refused, each as planning is shown it (§4:4-§4:5).
_REFUSAL_TEXT: Final = {
    TaskRefusal.UNKNOWN_TASK: "the Task Scheduler holds no such task",
    TaskRefusal.ANOTHER_PERSONS: "that task is another person's",
    TaskRefusal.NOT_ITS_SPAWN: (
        "this activation may cancel or replace only a task it spawned, since its "
        "input does not carry the person's authority"
    ),
    TaskRefusal.NOTHING_PENDING: "nothing of that task is pending",
    TaskRefusal.INVALID_WAIT: (
        "it waits on a task that is not the person's or not held, or it replaces a "
        "task without waiting on each task that one still waits on"
    ),
    TaskRefusal.CHAIN_LIMIT: "the chain of steps would exceed the chain limit",
    TaskRefusal.PENDING_LIMIT: (
        "it would take the person's pending scheduled tasks past the pending limit"
    ),
    TaskRefusal.ASSISTANTS_RULE: (
        "only a task the person asked for may repeat on a rule, and this "
        "activation's input does not carry the person's authority"
    ),
}
_NOT_OFFERED: Final = (
    "the Task Scheduler's calls are offered only to a person's activation started "
    "from a conversation, the line or the Task Scheduler"
)
_EARLIER_THAN_NOW: Final = "the instant it would fall due is earlier than now"
_NO_OFFSET: Final = "an instant states its UTC offset, such as 2026-10-25T20:00:00-04:00"
_ONE_WHEN: Final = "give at most one of at, delay_minutes, after and rule"
#: ADR-0340 §3:5 and §4:4's refusals, each made before the store is reached.
_OFFSET_AND_ZONE: Final = (
    "an instant states a UTC offset or names a zone, never both; a local time "
    "with no offset is read in the zone"
)
_UNKNOWN_ZONE: Final = "the zone is not an IANA zone name, such as Europe/Lisbon"
_ZONE_ALONE: Final = "a zone is named only with at or rule, which it is read in"
_UNTIL_BEFORE_FROM: Final = "the rule's until is earlier than its from"
_NO_OCCURRENCE: Final = "the rule yields no occurrence later than now before its until"
_RULE_DAYS: Final = "a weekly rule names one or more days of the week, and no other rule names any"
_RULE_TIME: Final = "a rule's time is a local time of day to the minute, such as 07:00"
_OFF_THE_LIST: Final = "it suggests a place that is not on this activation's place list"
_MALFORMED: Final = "the call's arguments are malformed"
_STORE_FAULT: Final = "the Task Scheduler could not be read or written"
_ZONE_UNREAD: Final = "the person's zone could not be read, so no time was read in it"


def _brief(text: str) -> str:
    """``text`` on one line, cut to :data:`_BRIEF_CHARS`."""
    flat = " ".join(text.split())
    return flat if len(flat) <= _BRIEF_CHARS else f"{flat[: _BRIEF_CHARS - 1]}…"


@dataclass(frozen=True, slots=True)
class TaskManagerLimits:
    """ADR-0350 §12:5's settings the Task Manager reads.

    Attributes:
        chain_limit: The longest chain of steps a spawn may extend (§9:7).
        pending_limit: The most pending occurrences one person may have (§9:8).
        listing_bound: The most items each part of a listing shows (§4:6, §10:2).
    """

    chain_limit: int
    pending_limit: int
    listing_bound: int


#: ADR-0361 §7:3: what a place an input taken by a take came from is said to be.
_TAKEN_FROM: Final = "a conversation an input this activation took came from"


class PlaceLists:
    """Build an activation's place list when it is shown (ADR-0350 §5:8, §5:11).

    It reads the conversation store for whether a conversation is gone, and asks
    ``line_connected`` whether the line is connected; the line's chat is the one the
    settings name, or none where no line is configured.
    """

    def __init__(
        self,
        *,
        conversations: ConversationStore,
        line: ChannelIdentity | None = None,
        line_connected: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        """Wire the builder.

        Args:
            conversations: The chat space, whose conversations are places.
            line: The line's chat, as the settings name it, or ``None`` with no line.
            line_connected: Whether the line is connected now; ``None`` reads it as
                connected wherever it is configured.
        """
        self._conversations = conversations
        self._line = line
        self._line_connected = line_connected

    async def shown(
        self,
        *,
        input_place: ChannelIdentity | None,
        suggested: Sequence[str] | None,
        taken: Sequence[ChannelIdentity] = (),
    ) -> tuple[ListedPlace, ...]:
        """The place list, as it stands now.

        Args:
            input_place: The place the activation's input came from.
            suggested: For an activation the Task Scheduler started, its task's suggested
                places, or an approval's, its asking work's (ADR-0361 §6:7); ``None`` for
                every other activation.
            taken: The places inputs the activation took by a take came from, each of
                which is on its list where it is not gone (ADR-0361 §7:3).

        Returns:
            The places, the hub chat's before the line's, each once.
        """
        places: list[ListedPlace] = []
        if suggested is None:
            if (
                input_place is not None
                and input_place.channel_type == "conversation"
                and await self._held(input_place)
            ):
                places.append(
                    ListedPlace(
                        input_place, _HUB_CHAT, "the conversation this activation's input came from"
                    )
                )
        else:
            for one in dict.fromkeys(suggested):
                channel = place_channel(one)
                if channel is None or channel.channel_type != "conversation":
                    continue
                if await self._held(channel):
                    places.append(
                        ListedPlace(channel, _HUB_CHAT, place_description(channel), suggested=True)
                    )
        listed = {one.channel for one in places}
        for channel in dict.fromkeys(taken):
            if (
                channel.channel_type == "conversation"
                and channel not in listed
                and await self._held(channel)
            ):
                places.append(ListedPlace(channel, _HUB_CHAT, _TAKEN_FROM))
        line = await self._connected_line()
        if line is not None:
            mark = suggested is not None and place_of(line) in suggested
            input_line = suggested is None and input_place == line
            places.append(
                ListedPlace(
                    line,
                    _TELEGRAM,
                    "the person's Telegram chat with their assistant"
                    + (", where this activation's input came from" if input_line else ""),
                    suggested=mark,
                )
            )
        return tuple(places)

    async def _held(self, channel: ChannelIdentity) -> bool:
        """Whether a conversation is still held: one deleted is gone (§5:8).

        A read that fails is no answer that it was deleted, so the conversation stays
        listed: where it is gone, the message written into it is refused, and the
        activation does not end as though it had spoken.
        """
        try:
            return await self._conversations.get(channel.instance_id) is not None
        except ConversationStoreError:
            _log.warning("place_list_unread", stage="planning", reason="store_failed")
            return True

    async def _connected_line(self) -> ChannelIdentity | None:
        """The line's chat, where the line is connected (§5:11)."""
        if self._line is None:
            return None
        if self._line_connected is None:
            return self._line
        try:
            return self._line if await self._line_connected() else None
        except Exception:  # whether it is connected is not known: it stays listed
            _log.warning("place_list_unread", stage="planning", reason="line_unknown")
            return self._line


@dataclass(frozen=True, slots=True)
class StatedWhen:
    """A spawn's when, as its arguments state it, resolved when the task is set.

    Attributes:
        when: The when the task holds.
        first_due_at: For a rule, the instant of its first occurrence, computed in the
            zone it is read in (ADR-0340 §4:5, §9:1); ``None`` for any other when.
    """

    when: TaskWhen
    first_due_at: datetime | None = None


_WHENS: Final = (AT_ARGUMENT, DELAY_ARGUMENT, AFTER_ARGUMENT, RULE_ARGUMENT)


def spawn_when(  # noqa: PLR0911 — each of the when's forms and refusals is a return of its own
    arguments: Mapping[str, FrozenJson], *, now: datetime, zone: ZoneInfo
) -> StatedWhen | str:
    """A spawn's when, from its arguments, or why it is refused (ADR-0350 §5, ADR-0340 §3-§4).

    A delay is resolved to an instant now, and a spawn naming no when falls due now. An
    instant states its UTC offset, or is a local date and time with none, read in the
    zone the spawn names and in ``zone`` where it names none (ADR-0340 §3:2). A rule
    names its zone, or follows the person's, and its first occurrence is computed here
    (§4:3, §4:5). Each is refused as *not done*, with the reason: an instant earlier than
    now (ADR-0350 §4:5); an offset with a zone, or a zone ``zoneinfo`` does not resolve
    (§3:5); a zone with no instant or rule to read in it; and a rule malformed, whose
    until is earlier than its from, or that yields no occurrence later than now (§4:4).

    Args:
        arguments: The spawn's arguments.
        now: The instant it is set at.
        zone: The person's zone (ADR-0340 §3:3).
    """
    stated = [name for name in _WHENS if name in arguments]
    if len(stated) > 1:
        return _ONE_WHEN
    named = arguments.get(ZONE_ARGUMENT)
    read_in = zone
    if named is not None:
        if not isinstance(named, str):
            return _MALFORMED
        if stated not in ([AT_ARGUMENT], [RULE_ARGUMENT]):
            return _ZONE_ALONE
        found = resolve_zone(named)
        if found is None:
            return _UNKNOWN_ZONE
        read_in = found
    if not stated:
        return StatedWhen(DueNow())
    if AT_ARGUMENT in arguments:
        return _instant(arguments[AT_ARGUMENT], now=now, zone=read_in, named=named is not None)
    if RULE_ARGUMENT in arguments:
        return _rule(arguments[RULE_ARGUMENT], now=now, zone=read_in, named=named)
    if DELAY_ARGUMENT in arguments:
        return _delay(arguments[DELAY_ARGUMENT], now=now)
    return _after(arguments[AFTER_ARGUMENT])


def _instant(  # noqa: PLR0911 — each refusal is a return of its own
    text: FrozenJson, *, now: datetime, zone: ZoneInfo, named: bool
) -> StatedWhen | str:
    """An instant, with its UTC offset or read in ``zone``, not earlier than now.

    ADR-0350 §5:2 and §4:5, ADR-0340 §3:2-§3:5: an offset and a named zone together are
    refused; a local time with no offset resolves in ``zone``, a gap to the first instant
    after it and a repeated hour to the earlier of the two.
    """
    if not isinstance(text, str):
        return _MALFORMED
    try:
        at = datetime.fromisoformat(text)
    except ValueError:
        return _MALFORMED
    if at.tzinfo is None:
        at = local_instant(at, zone)
    elif at.utcoffset() is None:
        return _NO_OFFSET
    elif named:
        return _OFFSET_AND_ZONE
    if at < now:
        return _EARLIER_THAN_NOW
    try:
        return StatedWhen(DueAt(at=at))
    except ValueError:
        return _MALFORMED


def _rule(
    stated: FrozenJson, *, now: datetime, zone: ZoneInfo, named: str | None
) -> StatedWhen | str:
    """A rule, from its parts, with its first occurrence computed in ``zone`` (ADR-0340 §4).

    Its zone is ``named``, the one the spawn names, or none, so it follows the person's
    (§4:3). Refused, as not done with the reason, where its parts are malformed, a
    weekly rule names no day or another names any, its until is earlier than its from,
    or it yields no occurrence later than now (§4:4).
    """
    rule = _rule_of(stated, named=named)
    if isinstance(rule, str):
        return rule
    first = first_occurrence(rule, zone, now=now)
    if first is None:
        return _NO_OCCURRENCE
    return StatedWhen(rule, first_due_at=first)


def _rule_of(stated: FrozenJson, *, named: str | None) -> DueOnRule | str:  # noqa: PLR0911 — each refusal is a return of its own
    """The rule a spawn's ``rule`` argument states, or why it is refused (§4:2, §4:4)."""
    if not isinstance(stated, Mapping) or not set(stated) <= _RULE_PARTS:
        return _MALFORMED
    kind = _rule_kind(stated.get(REPEATS_PART), stated.get(DAYS_PART, []))
    if isinstance(kind, str):
        return kind
    clock = _clock(stated.get(TIME_PART))
    if clock is None:
        return _RULE_TIME
    since = _day(stated.get(FROM_PART))
    until = _day(stated.get(UNTIL_PART))
    if isinstance(since, str) or isinstance(until, str):
        return _MALFORMED
    if since is not None and until is not None and until < since:
        return _UNTIL_BEFORE_FROM
    try:
        return DueOnRule(
            repeats=kind[0],
            days=kind[1],
            time_of_day=clock,
            zone=named,
            from_date=since,
            until_date=until,
        )
    except ValueError:
        return _MALFORMED


#: A rule argument's parts.
_RULE_PARTS: Final = frozenset({REPEATS_PART, DAYS_PART, TIME_PART, FROM_PART, UNTIL_PART})


def _rule_kind(
    repeats: FrozenJson, days: FrozenJson
) -> tuple[TaskRuleKind, tuple[RuleDay, ...]] | str:
    """A rule's kind and its days, or why they are refused (§4:2)."""
    kinds = {one.value: one for one in TaskRuleKind}
    week = {one.value: one for one in RuleDay}
    if not isinstance(repeats, str) or repeats not in kinds or not isinstance(days, list | tuple):
        return _MALFORMED
    if not all(isinstance(one, str) and one in week for one in days):
        return _MALFORMED
    named = tuple(week[str(one)] for one in days)
    kind = kinds[repeats]
    if (kind is TaskRuleKind.WEEKLY) != bool(named) or len(set(named)) != len(named):
        return _RULE_DAYS
    return kind, named


def _clock(text: FrozenJson) -> time | None:
    """A rule's local time of day, to the minute, or ``None`` where it is not one (§4:2)."""
    if not isinstance(text, str):
        return None
    try:
        clock = time.fromisoformat(text)
    except ValueError:
        return None
    if clock.tzinfo is not None or clock.second or clock.microsecond:
        return None
    return clock


def _day(text: FrozenJson) -> date | None | str:
    """A rule's from or until, a local date; ``None`` where it is not given (§4:4)."""
    if text is None:
        return None
    if not isinstance(text, str):
        return _MALFORMED
    try:
        return date.fromisoformat(text)
    except ValueError:
        return _MALFORMED


def _delay(minutes: FrozenJson, *, now: datetime) -> StatedWhen | str:
    """A delay from now, resolved to an instant when the task is set (§5:1)."""
    if isinstance(minutes, bool) or not isinstance(minutes, int | float) or not minutes > 0:
        return _MALFORMED
    try:
        return StatedWhen(DueAt(at=now + timedelta(minutes=float(minutes))))
    except OverflowError, ValueError:
        return _MALFORMED


def _after(named: FrozenJson) -> StatedWhen | str:
    """The hub event named tasks ending, by the tasks' ids (§5:4)."""
    if not isinstance(named, list | tuple) or not all(isinstance(one, str) for one in named):
        return _MALFORMED
    try:
        return StatedWhen(DueAfterTasks(tasks=tuple(str(one) for one in named)))
    except ValueError:
        return _MALFORMED


@dataclass(frozen=True, slots=True)
class TaskParent:
    """Where and when a task's parent, the activation that spawned it, started (§4:6).

    Attributes:
        channel: The place its input came from.
        started_at: When it started.
    """

    channel: ChannelIdentity
    started_at: datetime


class TaskManager:
    """The Task Manager's queries and commands, with one implementation each (§10:4).

    The engine builds it over the one plan store, the memory store the schedule's episodes
    are read from, and its own account of what runs; its stop is the engine's.
    """

    def __init__(  # noqa: PLR0913 — the two stores, the engine's three seams, the sensor's wake, the bounds, the zones, the clock and the id source
        self,
        *,
        plans: PlanStore,
        memory: MemoryStore,
        running: Callable[[], Iterable[ActivationState]],
        is_running: Callable[[str], bool],
        starting: Callable[[str], bool],
        wake: Callable[[], None],
        limits: TaskManagerLimits,
        zones: PersonZones,
        now: Clock,
        new_task_id: Callable[[], str] | None = None,
    ) -> None:
        """Wire the Task Manager.

        Args:
            plans: The plan store, which holds the Task Scheduler's content.
            memory: The memory store the schedule's episodes are read from (§7:9).
            running: The activations the engine holds as running.
            is_running: Whether an activation is running, admitted or pushed.
            starting: Whether an occurrence was pushed to an activation that is not yet
                admitted and that no stop has named, so it is about to start
                (ADR-0352 §3:4).
            wake: Wakes the sensor, which every write to a task does (§7:2).
            limits: §12:5's chain, pending and listing bounds.
            zones: The person's zone, read for the person each task and query is for,
                which the hub's renderings tell local time in (ADR-0340 §6:1).
            now: The clock a spawn's now is read from.
            new_task_id: Mints a scheduled task's id.
        """
        self._plans = plans
        self._memory = memory
        self._running = running
        self._is_running = is_running
        self._starting = starting
        self._wake = wake
        self._limits = limits
        self._zones = zones
        self._now = now
        self._new_task_id = new_task_id or (lambda: f"task:{uuid.uuid4().hex}")

    # --- the queries (§10:2) ---

    async def zone_of(self, person: str) -> ZoneInfo:
        """``person``'s zone, which their tasks' times are read and rendered in (§3:3)."""
        return await self._zones.of(person)

    async def listing(self, spawner: Spawner) -> TaskListing:
        """The list pull: the three queries, for the person ``spawner`` is for (§4:6).

        Raises:
            PlanningError: If the plan store cannot be read.
            MemoryStoreError: If the schedule's episodes cannot be read.
        """
        zone = await self.zone_of(spawner.person)
        return TaskListing(
            running=self.running(
                spawner.person,
                asker=spawner.activation_id,
                supply=spawner.supply,
                shown=spawner.sees_running,
                zone=zone,
            ),
            scheduled=await self.scheduled(spawner.person, zone=zone),
            recent=await self.recent(spawner.person, supply=spawner.supply, zone=zone),
            listed=True,
        )

    def running(
        self,
        person: str,
        *,
        asker: str | None,
        supply: TurnSupply | None,
        shown: bool = True,
        zone: ZoneInfo | None = None,
    ) -> tuple[ActivationEntry, ...]:
        """What is running for ``person``, live from the engine (§4:6, §10:2).

        ADR-0349 §6:2: each activation understanding's in-progress section would enter
        (§5:2-§5:5), as its entry shows it (§5:6), its input read through the peer view,
        so an outside one is withheld with its mark shown (§4:7); nothing to a viewer
        whose author is not established (``shown``). Newest first, bounded by the
        listing bound. Its times are told in ``zone``, the person's (ADR-0340 §6:1), and
        in the hub's where it is ``None``.
        """
        if not shown:
            return ()
        told = self._zones.default if zone is None else zone
        entries = self._running_entries(
            self._running(), asker=asker, person=person, supply=supply, zone=told
        )
        return tuple(entries[: self._limits.listing_bound])

    @staticmethod
    def _running_entries(
        running: Iterable[ActivationState],
        *,
        asker: str | None,
        person: str,
        supply: TurnSupply | None,
        zone: ZoneInfo,
    ) -> list[ActivationEntry]:
        """Each of ``running`` the list pull's running part would show, newest first."""
        states = {one.activation_id: one for one in running}
        entries: list[ActivationEntry] = []
        for entry in in_progress(states.values(), viewer=asker, person=person, supply=supply):
            state = states.get(entry.activation_id)
            started = None if state is None else state.started_at
            entries.append(
                ActivationEntry(
                    activation_id=entry.activation_id,
                    started="" if started is None else local_time(started, zone),
                    place=place_description(entry.channel),
                    status="running",
                    input=entry.input,
                    outside=entry.outside,
                    acted=entry.acted,
                    assistants=not entry.outside and parties_are_assistants(entry.parties),
                )
            )
        return entries

    async def scheduled(
        self, person: str, *, zone: ZoneInfo | None = None
    ) -> tuple[TaskEntry, ...]:
        """``person``'s pending scheduled tasks, each with its parent (§4:6, §10:2).

        Their times are told in ``zone``, or in ``person``'s, read here, where it is
        ``None`` (ADR-0340 §6:1).

        Raises:
            PlanningError: If the plan store cannot be read.
        """
        held = await self._plans.person_scheduled_tasks(person, [OccurrenceState.PENDING])
        told = await self.zone_of(person) if zone is None else zone
        shown = held[: self._limits.listing_bound]
        parents = await self.parents(shown)
        return tuple(self.entry(one, told, parent=parents.get(one.parent)) for one in shown)

    async def still_live(
        self,
        activation_id: str,
        *,
        person: str,
        viewer: str | None,
        supply: TurnSupply | None,
    ) -> StillLive:
        """What ``activation_id`` set up that is still live below it (ADR-0352 §3:1-§3:6).

        *Below* is ADR-0350 §9:6's walk, made as a read (§3:2): the tasks it spawned, and
        the tasks spawned by those tasks' activations in turn, whether or not those
        activations have ended. Each task with an occurrence pending is shown as the list
        pull shows one, with its parent's description (§3:3), in the order written; each
        activation running from a task below as the list pull's running part shows one,
        and one pushed and not yet admitted as starting under its task (§3:4), oldest
        first. A marked task and an outside input are withheld with their mark (§3:5).
        Each part shows at most the listing bound and counts the rest (§3:6). It reads
        only, and is called once the stop's record is written, or the activation was
        found ended or stopped. ``viewer``, the stop call's own activation, is never
        shown, and a running one ``supply`` does not admit is not shown, as the list pull
        shows neither.

        The person's zone is read first, and what runs below is read into entries in the
        walk's own step (:meth:`_below`), so nothing awaited after it, the parents' read
        included, can change what it shows as running or starting.

        Never raises but for a cancellation: where the tasks or the person's zone cannot
        be read, what it answers says it was not read.
        """
        try:
            zone = await self.zone_of(person)
            below = await self._below(
                activation_id,
                lambda tasks: self._live(
                    tasks, viewer=viewer, person=person, supply=supply, zone=zone
                ),
            )
        except PlanningError, PersonModelStoreError:
            _log.warning("stop_set_up_unread", stage="acting", reason="store_failed")
            return StillLive(read=False)
        pending = [task for task in below.tasks if task.pending]
        bound = self._limits.listing_bound
        shown = pending[:bound]
        parents = await self.parents(shown)
        tasks = tuple(self.entry(one, zone, parent=parents.get(one.parent)) for one in shown)
        return StillLive(
            tasks=tasks,
            more_tasks=len(pending) - len(shown),
            activations=below.activations[:bound],
            more_activations=max(0, len(below.activations) - bound),
        )

    def _live(
        self,
        tasks: Sequence[ScheduledTask],
        *,
        viewer: str | None,
        person: str,
        supply: TurnSupply | None,
        zone: ZoneInfo,
    ) -> tuple[ActivationEntry | StartingEntry, ...]:
        """Each activation running or starting from ``tasks``, as it is now, oldest first.

        Read in one synchronous step, into entries that nothing later changes: a running
        one as the list pull's running part shows it, and one pushed and not yet admitted
        as starting under its task (§3:4).
        """
        from_task = {one: task.id for task in tasks for one in task.activations}
        live = [one for one in self._running() if one.activation_id in from_task]
        running = self._running_entries(live, asker=viewer, person=person, supply=supply, zone=zone)
        held = {one.activation_id for one in live if not one.ended}
        starting = [
            StartingEntry(task_id=task)
            for one, task in from_task.items()
            if one not in held and one != viewer and self._starting(one)
        ]
        return (*reversed(running), *starting)

    async def _below(
        self,
        activation_id: str,
        live: Callable[[Sequence[ScheduledTask]], tuple[ActivationEntry | StartingEntry, ...]],
    ) -> _Below:
        """Every task below ``activation_id``, in the order written, and what runs from them.

        The walk finds every activation below, level by level; the tasks they spawned
        are then read in one read over all of them, which gives the store's order of
        writing across levels (§3:6): a child step's task written before a later direct
        spawn of the stopped activation is listed first.

        **The schedule moves on while it is read** (§3:1-§3:2). Where that read shows an
        activation the walk had not reached, pushed since and perhaps ended after
        spawning a step of its own, the walk goes on from it. Once it shows none, what
        runs and what is starting is read by ``live`` in one synchronous step, and the
        tasks are read once more: where they are as they were, nothing below that read
        reached spawned, started or ended between the schedule's read and what runs, so
        an activation ``live`` no longer found running had ended with nothing more below
        it. Where they moved, it all goes again. Every pass after the first is caused by
        a write below the stopped activation, which the chain and pending limits bound
        (ADR-0350 §9:7-§9:8), so it ends.

        Raises:
            PlanningError: If the plan store cannot be read.
        """
        walked = [activation_id]
        frontier = [activation_id]
        while True:
            while frontier:
                frontier = _unwalked(await self._plans.spawned_tasks(frontier), walked)
            ordered = await self._plans.spawned_tasks(walked)
            frontier = _unwalked(ordered, walked)
            if frontier:
                continue
            activations = live(ordered)
            again = await self._plans.spawned_tasks(walked)
            if _schedule_shape(again) == _schedule_shape(ordered):
                return _Below(tasks=again, activations=activations)
            frontier = _unwalked(again, walked)

    async def parents(self, tasks: Sequence[ScheduledTask]) -> dict[str, TaskParent]:
        """Where and when each of ``tasks``' parents started, from the record (§4:6, §9:4).

        A task's parent is the activation that spawned it, or on a replace the replaced
        task's, so where and when the task was set may describe the replacing spawn
        instead. Each is read only as its finished episode (ADR-0350 §6:6): no running
        activation's state is read through the pointer, and an open episode reaches no
        model (ADR-0286 §6:4). A parent still running, one whose episode is not held or
        came from no place, and every one where the episodes cannot be read, is left
        out, and its task is then described from where and when it was set, which is its
        parent's own unless a replace wrote it.
        """
        found: dict[str, TaskParent] = {}
        rest = sorted({one.parent for one in tasks})
        if not rest:
            return found
        try:
            read = without_open_episodes(
                await self._memory.get_many([f"activation:{one}" for one in rest])
            )
        except MemoryStoreError:
            _log.warning("task_parent_unread", stage="task_scheduler", reason="store_failed")
            return found
        for one in rest:
            record = read.get(f"activation:{one}")
            processing = record.processing_record if isinstance(record, EpisodicMemory) else None
            if processing is not None and processing.trigger.channel is not None:
                found[one] = TaskParent(processing.trigger.channel, processing.started_at)
        return found

    async def described(
        self, task: ScheduledTask, zone: ZoneInfo, *, spawner: Spawner | None = None
    ) -> TaskEntry:
        """``task`` as :meth:`entry` shows it, its parent read from the record (§4:6)."""
        parents = await self.parents((task,))
        return self.entry(task, zone, spawner=spawner, parent=parents.get(task.parent))

    async def recent(
        self, person: str, *, supply: TurnSupply | None, zone: ZoneInfo | None = None
    ) -> tuple[ActivationEntry, ...]:
        """The activations the Task Scheduler started for ``person`` that ended last (§7:9).

        Read from the schedule's episodes, newest first, bounded by the listing bound,
        their times told in ``zone``, or ``person``'s where it is ``None``. Each says
        where its messages went, read from their effect records (ADR-0350 §12:8), or
        nothing of it where those cannot be read.

        Raises:
            MemoryStoreError: If the episodes cannot be read.
        """
        told = await self.zone_of(person) if zone is None else zone
        page = await self._memory.channel_episodes(SCHEDULE, limit=self._limits.listing_bound)
        shown: list[ActivationEntry] = []
        for row in reversed(page.entries):
            record = row.record
            processing = record.processing_record
            if processing is None or processing.is_open:
                continue
            if activation_person(processing.trigger) != person:
                continue
            if supply is not None and not admitted_to_understanding(supply, (record,)):
                continue
            outside = holds_outside(processing.trigger, processing.understanding, processing.joined)
            payload = processing.trigger.payload
            text = getattr(payload, "text", None)
            status = _ended_text(processing.status, processing.reason)
            shown.append(
                ActivationEntry(
                    activation_id=processing.activation_id,
                    started=local_time(processing.started_at, told),
                    place=place_description(SCHEDULE),
                    status=status,
                    input=None if outside or not isinstance(text, str) else _brief(text),
                    outside=outside,
                )
            )
        return await self._where_written(shown)

    async def _where_written(
        self, entries: Sequence[ActivationEntry]
    ) -> tuple[ActivationEntry, ...]:
        """``entries``, each with where its messages went, from their effect records.

        A message done went into its place; one whose outcome is not known, unfinished or
        unknown, may have; one not done went nowhere (ADR-0306 §5:5). Where the records
        cannot be read, nothing is said of where any spoke.
        """
        if not entries:
            return ()
        try:
            effects = await self._plans.activation_effects([one.activation_id for one in entries])
        except PlanningError:
            _log.warning("task_messages_unread", stage="task_scheduler", reason="store_failed")
            return tuple(entries)
        wrote: dict[str, dict[str, None]] = {}
        unknown: dict[str, dict[str, None]] = {}
        for effect in effects:
            if effect.is_call or effect.place is None:
                continue
            if effect.outcome is ToolOutcome.SUCCEEDED:
                wrote.setdefault(effect.activation_id, {})[effect.place] = None
            elif effect.outcome is not ToolOutcome.FAILED:
                unknown.setdefault(effect.activation_id, {})[effect.place] = None
        told: list[ActivationEntry] = []
        for one in entries:
            done = tuple(wrote.get(one.activation_id, {}))
            maybe = tuple(
                place for place in unknown.get(one.activation_id, {}) if place not in done
            )
            told.append(replace(one, wrote_into=done, may_have_written_into=maybe))
        return tuple(told)

    def entry(
        self,
        task: ScheduledTask,
        zone: ZoneInfo,
        *,
        spawner: Spawner | None = None,
        parent: TaskParent | None = None,
    ) -> TaskEntry:
        """``task`` as a listing shows it, with the hub's renderings from its record.

        Its times in ``zone``, the person's, or its rule's own (ADR-0340 §6:1); for a
        rule, the rule in words (§8:2). For the task ``spawner``'s spawn wrote, the
        read-back too (§6:2), which says the line may still message the person where the
        line's chat is on the spawner's place list. Its parent is described from
        ``parent``, as :meth:`parents` read it, and from where and when the task was set
        where that is ``None`` (ADR-0350 §4:6).
        """
        occurrence = shown_occurrence(task)
        now = self._now()
        shown = task_zone(task, zone)
        started_in, started_at = (
            (task.set_in, task.set_at) if parent is None else (parent.channel, parent.started_at)
        )
        who = (
            "a scheduled step"
            if started_in.channel_type == SCHEDULE.channel_type
            else "the person's message"
            if task.author is ScheduledTaskAuthor.PERSON
            else "the assistant"
        )
        line = spawner is not None and any(
            (channel := place_channel(one)) is not None and channel.channel_type == "telegram"
            for one in spawner.places
        )
        return TaskEntry(
            task_id=task.id,
            state=outcome_text(occurrence),
            falls_due=when_text(task, zone, now=now),
            waits_on=task.when.tasks if isinstance(task.when, DueAfterTasks) else (),
            instruction=None if task.outside_content else _brief(task.instruction),
            outside=task.outside_content,
            places=tuple(place_of(one) for one in task.places),
            parent=task.parent,
            parent_text=(
                f"spawned by {who} in {place_description(started_in)}, "
                f"{local_time(started_at, shown)}"
            ),
            author=task.author.value,
            repeats=(
                rule_text(task.when, today=now.astimezone(shown).date(), zone=shown)
                if isinstance(task.when, DueOnRule)
                else None
            ),
            read_back=(None if spawner is None else read_back(task, zone, now=now, line=line)),
        )

    # --- the commands (§10:2) ---

    async def spawn(  # noqa: PLR0913 — the spawner, what it states, the record it is claimed under, and the claim's two
        self,
        spawner: Spawner,
        *,
        instruction: str,
        when: TaskWhen,
        places: tuple[ChannelIdentity, ...],
        replaces: str | None,
        effect: ActivationEffect,
        match: tuple[str, ...] | None,
        deliberate_repeat: bool,
        first_due_at: datetime | None = None,
    ) -> ScheduledTaskWrite:
        """Write a spawn's task, claiming its effect record in the one step (§3:3).

        ``first_due_at`` is a rule's first occurrence, as :func:`spawn_when` computed it
        in the zone the rule is read in (ADR-0340 §4:5, §9:5).

        Raises:
            ClaimStopped: If the store holds a stop record for the spawner.
            PlanningError: If the spawn does not validate or the store fails.
        """
        spawn = TaskSpawn(
            id=self._new_task_id(),
            person=spawner.person,
            author=spawner.author,
            when=when,
            places=places,
            instruction=instruction,
            set_in=spawner.set_in,
            set_at=self._now(),
            outside_content=spawner.read_outside_content,
            replaces=replaces,
            first_due_at=first_due_at,
        )
        written = await self._plans.write_scheduled_task(
            spawn,
            effect,
            match=match,
            deliberate_repeat=deliberate_repeat,
            replace_any=spawner.users_authority,
            chain_limit=self._limits.chain_limit,
            pending_limit=self._limits.pending_limit,
        )
        if written.answer is TaskWriteAnswer.WRITTEN:
            self._wake()
            if replaces is not None:
                await self.tidy([replaces])
        return written

    async def cancel(
        self, task_id: str, *, person: str | None = None, spawned_by: str | None = None
    ) -> ScheduledTaskCancel:
        """Cancel what is pending of a task (§9:5); it stops nothing running.

        ``person`` and ``spawned_by`` are §4:4's checks for planning's cancel; the Task
        Manager's command gives neither.

        Raises:
            PlanningError: If the store fails.
        """
        cancelled = await self._plans.cancel_scheduled_task(
            task_id, person=person, spawned_by=spawned_by
        )
        if cancelled.task is not None:
            self._wake()
            await self.tidy([task_id])
        return cancelled

    async def replace(
        self, task_id: str, *, instruction: str, when: TaskWhen
    ) -> ScheduledTaskWrite:
        """The Task Manager's replace command, from outside (§9:4, §10:2).

        A structured act naming one operation (§10:5): it writes the new task, which takes
        the replaced task's parent, suggested places and chain length, claimed under an
        effect record of the command's own, and is the person's act. A rule's first
        occurrence is computed in its own zone or the person's (ADR-0340 §4:5).

        Raises:
            PlanningError: If the store fails, the task is not held, a rule names a zone
                ``zoneinfo`` does not resolve (ADR-0340 §3:5), or it yields no occurrence
                later than now (§4:4). Nothing is written.
            PersonModelStoreError: If the person's zone cannot be read, which a rule
                naming none is computed in. Nothing is written.
        """
        held = await self._plans.scheduled_tasks([task_id])
        if not held:
            msg = f"the Task Scheduler holds no task {task_id}"
            raise PlanningError(msg)
        replaced = held[0]
        first = None
        if isinstance(when, DueOnRule):
            if when.zone is None:
                zone = await self.zone_of(replaced.person)
            else:
                named = resolve_zone(when.zone)
                if named is None:
                    msg = "the rule names a zone that is not an IANA zone name (ADR-0340 §3:5)"
                    raise PlanningError(msg)
                zone = named
            first = first_occurrence(when, zone, now=self._now())
            if first is None:
                msg = "the rule yields no occurrence later than now (ADR-0340 §4:4)"
                raise PlanningError(msg)
        command = str(uuid.uuid4())
        effect = _command_effect(command, self._now())
        spawner = Spawner(
            activation_id=command,
            person=replaced.person,
            users_authority=True,
            set_in=replaced.set_in,
        )
        written = await self.spawn(
            spawner,
            instruction=instruction,
            when=when,
            places=(),
            replaces=task_id,
            effect=effect,
            match=None,
            deliberate_repeat=False,
            first_due_at=first,
        )
        if written.answer is TaskWriteAnswer.WRITTEN:
            await self._plans.finish_activation_effect(effect.id, ToolOutcome.SUCCEEDED)
        return written

    # --- keeping the schedule (§7:8) ---

    async def tidy(self, task_ids: Iterable[str]) -> None:
        """Remove each named task once nothing of it or below it is live (§7:8).

        A task whose parent still runs is kept. Each task removed may let the task above
        it, and the tasks it waited on, go in turn. Never raises but for a cancellation:
        a removal not made now is made at a later tidy, and nothing reads a task kept a
        little longer as anything but kept.
        """
        # A task kept now may go once another in the walk is removed, so one is read
        # again whenever a removal names it: each entry after the first is added by a
        # removal, and the store holds finitely many tasks, so the walk ends.
        work = list(dict.fromkeys(task_ids))
        while work:
            task_id = work.pop()
            try:
                held = await self._plans.scheduled_tasks([task_id])
                if not held or self._is_running(held[0].parent):
                    continue
                task = held[0]
                if not await self._plans.remove_scheduled_task(task_id):
                    continue
                above = await self._plans.scheduled_lineage(task.parent)
            except PlanningError:
                _log.warning("task_tidy_failed", stage="task_scheduler", reason="store_failed")
                continue
            if above:
                work.append(above[-1].id)
            if isinstance(task.when, DueAfterTasks):
                work.extend(task.when.tasks)

    async def parent_ended(self, activation_id: str) -> None:
        """An activation ended: the tasks it spawned may now be removed (§7:8)."""
        try:
            spawned = await self._plans.spawned_tasks([activation_id])
        except PlanningError:
            _log.warning("task_tidy_failed", stage="task_scheduler", reason="store_failed")
            return
        if spawned:
            await self.tidy(one.id for one in spawned)


@dataclass(frozen=True, slots=True)
class _Below:
    """What :meth:`TaskManager._below` read: the tasks, and what ran or was starting."""

    tasks: tuple[ScheduledTask, ...]
    activations: tuple[ActivationEntry | StartingEntry, ...]


def _schedule_shape(tasks: Iterable[ScheduledTask]) -> tuple[object, ...]:
    """What of ``tasks`` a walk reads: each task and its occurrences' states and pushes."""
    return tuple(
        (task.id, tuple((one.number, one.state, one.activations) for one in task.occurrences))
        for task in tasks
    )


def _unwalked(tasks: Iterable[ScheduledTask], walked: list[str]) -> list[str]:
    """Each activation ``tasks`` were pushed to that ``walked`` lacks, now added to it."""
    found: list[str] = []
    for task in tasks:
        for one in task.activations:
            if one not in walked:
                walked.append(one)
                found.append(one)
    return found


def _ended_text(status: ProcessingStatus | None, reason: ProcessingReason | None) -> str:
    """How an ended activation's episode froze, in words."""
    if status is None:
        return "ended"
    return status.value if reason is None else f"{status.value} ({reason.value})"


def _command_effect(command: str, at: datetime) -> ActivationEffect:
    """The effect record a Task Manager's replace is claimed under (§10:2).

    A call's effect names the round that proposed it (ADR-0307 §10); the command's is
    its own, named for it.
    """
    return ActivationEffect(
        id=f"effect:{uuid.uuid4().hex}",
        activation_id=command,
        round=f"command:{command}",
        capability=SPAWN_CAPABILITY,
        values_digest="0" * 64,
        decision_id=f"command:{command}",
        claimed_at=at,
    )


class ScheduledTaskCalls:
    """Acting's runner for spawn, cancel and the list pull (ADR-0350 §4:3, §10:4).

    Structurally acting's ``OwnRecordsCalls`` and its ``ClaimingOwnRecordsCalls``: each
    call runs directly against the plan store, through the one :class:`TaskManager`, and
    is awaited to its end. Who calls is read from :func:`current_spawner`, which the
    phases open around acting, never from what the call carries.

    **Under a ticket** (ADR-0362 §3:3-§3:5), a call runs in the work holding the ticket's
    input, the approval's own activation included, and is the person's: its input's
    authority is read as carried for that call alone. A spawn's write spends the ticket
    in its one step, and its refusal of the ticket writes nothing.
    """

    def __init__(self, *, manager: TaskManager, now: Clock) -> None:
        """Wire the runner.

        Args:
            manager: The Task Manager, whose operations the calls are.
            now: The clock a delay and an instant are read against.
        """
        self._manager = manager
        self._now = now

    async def run(self, call: ToolCall) -> OwnRecordsAnswer:
        """Run a cancel or a list pull; a spawn reaches :meth:`run_claiming` alone."""
        spawner = _caller(call)
        if spawner is None:
            return NotDone(reason=_NOT_OFFERED)
        capability = str(call.request.tool.capability)
        try:
            if capability == LIST_TASKS_CAPABILITY:
                listing = await self._manager.listing(spawner)
                return ToolResult(outcome=ToolOutcome.SUCCEEDED, output=encode_listing(listing))
            if capability == CANCEL_TASK_CAPABILITY:
                return await self._cancel(spawner, call.request.parameters)
        except PlanningError, MemoryStoreError:
            _log.warning("task_call_not_done", stage="acting", reason="store_failed")
            return NotDone(reason=_STORE_FAULT)
        except PersonModelStoreError:
            return NotDone(reason=_ZONE_UNREAD)
        return NotDone(reason=_MALFORMED)

    async def _cancel(
        self, spawner: Spawner, arguments: Mapping[str, FrozenJson]
    ) -> OwnRecordsAnswer:
        task_id = arguments.get(TASK_ARGUMENT)
        if not isinstance(task_id, str) or not task_id.strip():
            return NotDone(reason=_MALFORMED)
        # Read before the cancel is written, so a zone that cannot be read leaves it unmade.
        zone = await self._manager.zone_of(spawner.person)
        cancelled = await self._manager.cancel(
            task_id,
            person=spawner.person,
            spawned_by=None if spawner.users_authority else spawner.activation_id,
        )
        if cancelled.reason is not None or cancelled.task is None:
            reason = TaskRefusal.UNKNOWN_TASK if cancelled.reason is None else cancelled.reason
            _log.info("task_call_not_done", stage="acting", reason=reason.value)
            return NotDone(reason=_REFUSAL_TEXT[reason])
        listing = TaskListing(cancelled=await self._manager.described(cancelled.task, zone))
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, output=encode_listing(listing))

    async def _stated(
        self, spawner: Spawner, arguments: Mapping[str, FrozenJson]
    ) -> tuple[ZoneInfo, StatedWhen] | str:
        """The person's zone and the spawn's when read in it, or why it is refused."""
        try:
            zone = await self._manager.zone_of(spawner.person)
        except PersonModelStoreError:
            # ADR-0340 §3:3: no zone is guessed, so nothing is read or written in one.
            return _ZONE_UNREAD
        stated = spawn_when(arguments, now=self._now(), zone=zone)
        return stated if isinstance(stated, str) else (zone, stated)

    async def run_claiming(  # noqa: PLR0911 — each of §4:5's refusals is a return of its own
        self,
        call: ToolCall,
        effect: ActivationEffect,
        *,
        match: tuple[str, ...] | None,
        deliberate_repeat: bool,
    ) -> ClaimingAnswer:
        """Run a spawn, its task and its effect claim written in one step (§3:3).

        Refused, writing nothing, where its instant is earlier than now, it suggests a
        place off its activation's list, or the store refuses it (§4:5); and on ADR-0340
        §3:5's and §4:4's grounds. A local time and a rule are read in the person's zone,
        or the one the spawn names, and the result carries the read-back (§6:2).

        Raises:
            ClaimStopped: If the store holds a stop record for the spawning activation.
        """
        spawner = _caller(call)
        if spawner is None or str(call.request.tool.capability) != SPAWN_CAPABILITY:
            return Unwritten(reason=_NOT_OFFERED)
        arguments = call.request.parameters
        instruction = arguments.get(INSTRUCTION_ARGUMENT)
        if not isinstance(instruction, str) or not instruction.strip():
            return Unwritten(reason=_MALFORMED)
        read = await self._stated(spawner, arguments)
        if isinstance(read, str):
            return Unwritten(reason=read)
        zone, stated = read
        places = _suggested(spawner, arguments)
        if isinstance(places, str):
            return Unwritten(reason=places)
        replaces = arguments.get(REPLACES_ARGUMENT)
        if replaces is not None and not isinstance(replaces, str):
            return Unwritten(reason=_MALFORMED)
        try:
            written = await self._manager.spawn(
                spawner,
                instruction=instruction,
                when=stated.when,
                places=places,
                replaces=replaces,
                effect=effect,
                match=match,
                deliberate_repeat=deliberate_repeat,
                first_due_at=stated.first_due_at,
            )
        except ValueError:
            return Unwritten(reason=_MALFORMED)
        refused = _refused(written)
        if refused is not None:
            return refused
        assert written.task is not None  # noqa: S101 — a write not refused carries its task
        listing = TaskListing(
            spawned=await self._manager.described(written.task, zone, spawner=spawner)
        )
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, output=encode_listing(listing))


def _refused(written: ScheduledTaskWrite) -> ClaimingAnswer | None:
    """What a spawn's write that wrote nothing answers acting, or ``None`` where it wrote.

    The backstop's and the spend's answers as a claim's; the ticket's refusal in the words
    a ticket's refusal of any other call is said in (ADR-0362 §3:1); and a refusal as not
    done with its reason (§4:5).
    """
    if written.answer is TaskWriteAnswer.ALREADY_DONE:
        return ActivationEffectClaim.ALREADY_DONE
    if written.answer is TaskWriteAnswer.ALREADY_USED:
        return ActivationEffectClaim.ALREADY_USED
    if written.answer is TaskWriteAnswer.TICKET_REFUSED and written.ticket is not None:
        # Nothing was written, so the ticket is as it was.
        _log.info("task_call_not_done", stage="acting", reason=f"ticket_{written.ticket.value}")
        return Unwritten(reason=TICKET_CLAIM_TEXT[written.ticket])
    if written.task is None:
        reason = TaskRefusal.UNKNOWN_TASK if written.reason is None else written.reason
        _log.info("task_call_not_done", stage="acting", reason=reason.value)
        return Unwritten(reason=_REFUSAL_TEXT[reason])
    return None


def _caller(call: ToolCall) -> Spawner | None:
    """Who calls the Task Scheduler, as :func:`current_spawner` holds it, for ``call`` alone.

    ADR-0362 §3:5: for a call run under a ticket, the rules reading whether the calling
    activation's input carries the person's authority read it as carried, for that call
    alone: the task it spawns is the person's (ADR-0350 §3:7), and it may replace or cancel
    any of the person's tasks (§4:4). The person approved that exact call on its card.
    """
    spawner = current_spawner()
    approval = call.decision.approval
    if spawner is None or approval is None or not isinstance(approval.how, TapOnCard):
        return spawner
    return replace(spawner, users_authority=True)


def _suggested(
    spawner: Spawner, arguments: Mapping[str, FrozenJson]
) -> tuple[ChannelIdentity, ...] | str:
    """The places a spawn suggests, each on its activation's list, or why not (§5:6).

    A spawn stating none from an activation the Task Scheduler started carries its own
    task's suggested places forward.
    """
    named = arguments.get(PLACES_ARGUMENT)
    if named is None:
        chosen = spawner.carried
    elif isinstance(named, list | tuple) and all(isinstance(one, str) for one in named):
        chosen = tuple(str(one) for one in named)
        if any(one not in spawner.places for one in chosen):
            return _OFF_THE_LIST
    else:
        return _MALFORMED
    channels: list[ChannelIdentity] = []
    for one in dict.fromkeys(chosen):
        channel = place_channel(one)
        if channel is None:
            return _MALFORMED
        channels.append(channel)
    return tuple(channels)


@dataclass(frozen=True, slots=True)
class TaskSchedulerSeams:
    """What the composition root hands the engine for the Task Scheduler (ADR-0350 §12:5).

    Attributes:
        limits: The chain, pending and listing bounds.
        recheck: The sensor's recheck interval (§7:2).
        lateness_grace: How long after it was due an occurrence may be pushed before its
            input says it is late (§8:9).
        push_limit: The most times one occurrence is pushed (§8:5).
        zone: The IANA name of ``Settings.timezone``, the zone a person's times are read
            and rendered in where their profile sets none (ADR-0340 §3:3).
        persons: The people whose pushed occurrences a restart settles (§8:1).
    """

    limits: TaskManagerLimits
    recheck: timedelta
    lateness_grace: timedelta
    push_limit: int
    zone: str
    persons: tuple[str, ...]
