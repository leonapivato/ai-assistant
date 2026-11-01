"""The Task Scheduler's declarations: its kind, its three capabilities and its shapes (ADR-0350).

The **Task Scheduler** is a built-in channel with exactly one place, **the schedule**
(§2:1). It is a medium the hub hosts (§2:2): it holds the scheduled tasks every spawn
writes, and the assistant reaches it only through its sensor
(:mod:`~ai_assistant.orchestration.task_sensor`) and its actuator, the direct write a
spawn and a cancel make against the plan store (§4:3). Its content is held in the plan
store, apart from the assistant's memory: recall does not search it, and consolidation
and the observer do not read it (§2:3). It is fully private: its kind takes no spoke on
any device, and a person reaches it only through the Task Manager (§2:4, §10).

This module is what the rest of the package shares of it, and runs nothing:

- **Its kind** (:data:`TASK_SCHEDULER_KIND`, §2:6), in
  :class:`~ai_assistant.orchestration.channel_kinds.ChannelKind`'s shape: its place runs
  activations side by side, it takes no message from a person or from the assistant,
  shows no running work, expects no reply, pushes and can be pulled, and its place's
  window is a task's lineage (§6:5). ``core``'s register holds its origin per input
  (§2:7): ``assistant``, or ``outside`` for a task carrying the outside-content mark.
- **The three capabilities** planning is offered (§4:1): :data:`SPAWN`, which may name a
  task it replaces; :data:`CANCEL_TASK`; and :data:`LIST_TASKS`, the list pull. Each
  declares the effect *the assistant's own records*, never leaves the hub and never has
  an unknown outcome. Spawn and cancel write the person's tier; the list pull writes
  nothing, so it is a pure read (ADR-0341 §2:1).
- **The spawner** (:class:`Spawner`), what the phases know of the activation calling a
  spawn, handed to the runner through :func:`spawning` around acting.
- **The listing** (:class:`TaskListing`), the shape a list pull, a spawn and a cancel
  answer in, which the phases render to planning under ``T``, ``E`` and ``L`` labels.
- **The hub's renderings**: of when a task falls due, of a task's parent (§4:6), of the
  input a due occurrence's activation is given (§6:2) and of its lineage window (§6:5),
  each in the person's zone, or a rule's own (ADR-0340 §6:1); and the **read-back**, a
  spawn's rendering of the task it wrote (ADR-0340 §6:2).

**Names** (§2:8): the channel is the *Task Scheduler* in full, its items *scheduled
tasks*; "the scheduler" stays ADR-0083 §7's housekeeping loop.
"""

from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, cast

from ai_assistant.core.channel_validation import APPROVALS, TASK_SCHEDULER
from ai_assistant.core.config import Settings
from ai_assistant.core.types import (
    CapabilityEffect,
    CapabilityResult,
    ChannelIdentity,
    CostBasis,
    DataTier,
    DueAfterTasks,
    DueAt,
    DueNow,
    DueOnRule,
    Idempotency,
    LabelKind,
    OccurrenceState,
    ProcessingReason,
    ProcessingStatus,
    Reversibility,
    RiskLevel,
    RuleDay,
    ScheduledTaskAuthor,
    TaskRuleKind,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.orchestration.channel_kinds import (
    Audience,
    ChannelKind,
    Direction,
    Reach,
    WindowSource,
    place_of,
)
from ai_assistant.orchestration.outside_content import holds_outside
from ai_assistant.orchestration.task_rules import (
    clock_text,
    computed_elsewhere,
    day_text,
    rule_text,
    task_zone,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from ai_assistant.core.types import (
        EpisodicMemory,
        FrozenJson,
        FrozenJsonValue,
        ScheduledOccurrence,
        ScheduledTask,
    )
    from ai_assistant.orchestration.disclosure import TurnSupply

__all__ = [
    "CANCEL_TASK",
    "CANCEL_TASK_CAPABILITY",
    "LIST_TASKS",
    "LIST_TASKS_CAPABILITY",
    "SCHEDULE",
    "SPAWN",
    "SPAWNING_KINDS",
    "SPAWN_CAPABILITY",
    "TASK_SCHEDULER_CALLS",
    "TASK_SCHEDULER_CAPABILITIES",
    "TASK_SCHEDULER_DESCRIPTION",
    "TASK_SCHEDULER_KIND",
    "TASK_SCHEDULER_LABEL_ARGUMENTS",
    "ActivationEntry",
    "LineageStep",
    "ListedPlace",
    "Spawner",
    "StartingEntry",
    "StillLive",
    "TaskEntry",
    "TaskListing",
    "current_spawner",
    "decode_listing",
    "encode_listing",
    "lineage_occurrence",
    "lineage_steps",
    "local_time",
    "occurrence_outcome",
    "outcome_text",
    "place_description",
    "read_back",
    "shown_occurrence",
    "spawning",
    "task_input",
    "when_text",
]

#: The schedule, the Task Scheduler's one place (ADR-0350 §2:1). Every activation it
#: starts is admitted on it, so its episode is indexed by it (§7:9, ADR-0292 §10:5).
SCHEDULE: Final = ChannelIdentity(channel_type=TASK_SCHEDULER, instance_id="schedule")

#: What planning is shown of the schedule's place (ADR-0292 §8:1), for an activation the
#: Task Scheduler started: no one is waiting on it, and its messages go into the places
#: on its place list.
TASK_SCHEDULER_DESCRIPTION: Final = (
    "The Task Scheduler: a scheduled task fell due and started this activation. No one "
    "is waiting on a reply here; a message you write goes into the one place on your "
    "place list that it names."
)

#: ADR-0350 §2:6: what the Task Scheduler's kind declares, each row in the ADR-0292
#: clause its name gives. Its window is a task's lineage, bounded by the chain limit
#: (§6:5, §9:7), whose default is the size declared here.
TASK_SCHEDULER_KIND: Final = ChannelKind(
    channel_type=TASK_SCHEDULER,
    channels="exactly one, built in, the Task Scheduler",
    direction=Direction.IN,
    reach=Reach.BOTH,
    input="a scheduled task's occurrence falling due",
    push_filter=None,
    authors=(
        "a task's author, the person or the assistant, stated by the hub from the record; "
        "no author is established as the user"
    ),
    places="exactly one, the schedule",
    window=WindowSource.MEDIUM,
    window_items=int(Settings.model_fields["task_scheduler_chain_limit"].default),
    sent="nothing: its place takes no message from a person or from the assistant",
    description=TASK_SCHEDULER_DESCRIPTION,
    text_only=True,
    message_limit=None,
    audience=Audience.PRIVATE,
    approval_giver=None,
)

#: ADR-0350 §3:4: the kinds whose activations are offered spawn, where they are a
#: person's: a conversation's, the line's and the Task Scheduler's own.
SPAWNING_KINDS: Final = frozenset({"conversation", "telegram", TASK_SCHEDULER})

# --- the three capabilities (ADR-0350 §4:1) -----------------------------------------------

SPAWN_CAPABILITY: Final = "spawn"
CANCEL_TASK_CAPABILITY: Final = "cancel_task"
LIST_TASKS_CAPABILITY: Final = "list_tasks"

#: Every capability this module declares.
TASK_SCHEDULER_CAPABILITIES: Final = frozenset(
    {SPAWN_CAPABILITY, CANCEL_TASK_CAPABILITY, LIST_TASKS_CAPABILITY}
)

#: Spawn's arguments.
INSTRUCTION_ARGUMENT: Final = "instruction"
AT_ARGUMENT: Final = "at"
DELAY_ARGUMENT: Final = "delay_minutes"
AFTER_ARGUMENT: Final = "after"
PLACES_ARGUMENT: Final = "places"
REPLACES_ARGUMENT: Final = "replaces"
#: ADR-0340 §8:1's two: a rule, and the zone a local time or a rule is read in.
RULE_ARGUMENT: Final = "rule"
ZONE_ARGUMENT: Final = "zone"
#: A rule's parts.
REPEATS_PART: Final = "repeats"
DAYS_PART: Final = "days"
TIME_PART: Final = "time"
FROM_PART: Final = "from"
UNTIL_PART: Final = "until"
#: Cancel's one argument.
TASK_ARGUMENT: Final = "task"


def _declared(  # noqa: PLR0913 — the capability, its words, its schema, and the three properties that differ between them
    capability: str,
    description: str,
    schema: dict[str, FrozenJson],
    *,
    writes: bool,
    safe_to_repeat: bool,
    idempotency: Idempotency,
) -> ToolDefinition:
    """One capability's declaration, the five properties as ADR-0350 §4:1 rules them.

    ``effect=OWN_RECORDS``, ``leaves_hub=False``, ``outcome_can_be_unknown=False`` and
    ``result=NO_OUTSIDE_TEXT``, for each of the three: what a call returns is the hub's
    own rendering of the stored record, with any text resting on outside content withheld
    (§4:7). Spawn and cancel write the person's tier; the list pull writes nothing.
    """
    return ToolDefinition(
        id=capability,
        capability=capability,
        description=description,
        risk_level=RiskLevel.LOW,
        # A write can be cancelled or replaced; a read has nothing to reverse.
        reversibility=Reversibility.RECOVERABLE if writes else Reversibility.REVERSIBLE,
        side_effecting=True,
        reads=(DataTier.PERSONAL,),
        writes=(DataTier.PERSONAL,) if writes else (),
        discloses=(),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=idempotency,
        effect=CapabilityEffect.OWN_RECORDS,
        leaves_hub=False,
        result=CapabilityResult.NO_OUTSIDE_TEXT,
        outcome_can_be_unknown=False,
        safe_to_repeat=safe_to_repeat,
        parameters_schema=schema,
    )


def _labels(description: str) -> dict[str, FrozenJson]:
    return {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
        "minItems": 1,
        "description": description,
    }


SPAWN: Final = _declared(
    SPAWN_CAPABILITY,
    (
        "Set up work that runs later or separately: a scheduled task, which starts an "
        "activation of its own when it falls due, reading what it carries. Spawn only "
        "work that runs later or separately. Give at most one of at, delay_minutes, "
        "after and rule; with none it falls due now. A task suggests only places on "
        "your place list. A task you were shown by its T label is replaced by one "
        'spawn naming it in replaces; find any other with list_tasks first. "Snooze '
        '10 minutes" or "again tomorrow", after a task\'s message, is a new spawn: a '
        "one-off task with the same instruction, written from what you were shown of "
        "the episode that wrote the message, suggesting the place the person said it "
        "in. Skipping a rule's next occurrence (\"skip tomorrow's\") is a spawn "
        "replacing it with the same rule from the local date after the skipped one, "
        'or its cancel where none would follow before its until. "Tomorrow at 9 '
        'instead" is that skip and a one-off task at the new time, in the same round. '
        "Write a local time with no UTC offset unless the person named one, and give "
        "a zone only where the person named one. Say a task back from its read_back, "
        "never from your own reckoning of the time. Where the words could mean more "
        "than one task, ask which."
    ),
    {
        "type": "object",
        "properties": {
            INSTRUCTION_ARGUMENT: {
                "type": "string",
                "minLength": 1,
                "maxLength": 4000,
                "description": "What the task's activation is to do, in your own words.",
            },
            AT_ARGUMENT: {
                "type": "string",
                "minLength": 1,
                "description": (
                    "When it falls due: an ISO 8601 local date and time with no offset, "
                    "such as 2026-10-25T20:00, read in the person's zone, or in zone; or "
                    "an instant with its UTC offset, such as 2026-10-25T20:00:00-04:00."
                ),
            },
            DELAY_ARGUMENT: {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "When it falls due: this many minutes from now.",
            },
            AFTER_ARGUMENT: _labels(
                "When it falls due: once every one of these tasks has ended, by T label."
            ),
            PLACES_ARGUMENT: {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "description": "The places it suggests speaking in, by L label.",
            },
            REPLACES_ARGUMENT: {
                "type": "string",
                "minLength": 1,
                "description": "A pending task this one replaces, by T label.",
            },
            RULE_ARGUMENT: {
                "type": "object",
                "description": (
                    "When it falls due, again and again: a rule, at a local time of day in "
                    "the person's zone, or in zone. Only for a task the person asked for."
                ),
                "properties": {
                    REPEATS_PART: {
                        "type": "string",
                        "enum": [one.value for one in TaskRuleKind],
                        "description": "Every day, Monday to Friday, or weekly on days.",
                    },
                    DAYS_PART: {
                        "type": "array",
                        "items": {"type": "string", "enum": [one.value for one in RuleDay]},
                        "minItems": 1,
                        "description": "The days of the week a weekly rule falls on.",
                    },
                    TIME_PART: {
                        "type": "string",
                        "minLength": 1,
                        "description": "The local time of day, 24-hour, such as 07:00.",
                    },
                    FROM_PART: {
                        "type": "string",
                        "minLength": 1,
                        "description": "A local date, such as 2026-10-27, before which none falls.",
                    },
                    UNTIL_PART: {
                        "type": "string",
                        "minLength": 1,
                        "description": "The last local date one may fall on, such as 2026-11-30.",
                    },
                },
                "required": [REPEATS_PART, TIME_PART],
                "additionalProperties": False,
            },
            ZONE_ARGUMENT: {
                "type": "string",
                "minLength": 1,
                "description": (
                    "The IANA zone at or rule is read in, such as Europe/Lisbon, only where "
                    "the person named one."
                ),
            },
        },
        "required": [INSTRUCTION_ARGUMENT],
        "additionalProperties": False,
    },
    writes=True,
    safe_to_repeat=False,
    idempotency=Idempotency.NONE,
)
"""``spawn``: write a scheduled task, which may replace a pending one (ADR-0350 §4:1, §9:4)."""

CANCEL_TASK: Final = _declared(
    CANCEL_TASK_CAPABILITY,
    (
        "Cancel what is still pending of a scheduled task. It stops nothing already "
        "running. A task you were shown by its T label is cancelled by one call; find "
        "any other with list_tasks first. Skipping a one-off task is its cancel. "
        '"Done" or "I already took it" before a task\'s message is that skip, and '
        "after its message is no call. Cancel exactly what the person's words cover, "
        "by the labels you were shown, and keep the rest; where the words could mean "
        "more than one task, ask which."
    ),
    {
        "type": "object",
        "properties": {
            TASK_ARGUMENT: {
                "type": "string",
                "minLength": 1,
                "description": "The task, by its T label.",
            }
        },
        "required": [TASK_ARGUMENT],
        "additionalProperties": False,
    },
    writes=True,
    safe_to_repeat=True,
    idempotency=Idempotency.NATURAL,
)
"""``cancel_task``: end every pending occurrence of a task (ADR-0350 §4:1, §9:5)."""

LIST_TASKS: Final = _declared(
    LIST_TASKS_CAPABILITY,
    (
        "List the person's work: what is running, the scheduled tasks still pending, "
        "and the scheduled work that ended most recently. Use it to find a task you "
        "were not shown by its T label before you replace or cancel it."
    ),
    {"type": "object", "properties": {}, "additionalProperties": False},
    writes=False,
    safe_to_repeat=True,
    idempotency=Idempotency.NATURAL,
)
"""``list_tasks``: the list pull (ADR-0350 §4:1, §4:6)."""

#: The three declarations, in the order they are offered.
TASK_SCHEDULER_CALLS: Final = (SPAWN, CANCEL_TASK, LIST_TASKS)

#: Which of the calls' arguments name things by label (ADR-0307 §5:2): planning maps each
#: to its id, and refuses whole a call naming a label it was never shown (§5:3).
TASK_SCHEDULER_LABEL_ARGUMENTS: Final[Mapping[str, Mapping[str, LabelKind]]] = {
    SPAWN_CAPABILITY: {
        AFTER_ARGUMENT: LabelKind.SCHEDULED_TASK,
        PLACES_ARGUMENT: LabelKind.PLACE,
        REPLACES_ARGUMENT: LabelKind.SCHEDULED_TASK,
    },
    CANCEL_TASK_CAPABILITY: {TASK_ARGUMENT: LabelKind.SCHEDULED_TASK},
}


# --- the place list (ADR-0350 §5:10-§5:13) -------------------------------------------------


@dataclass(frozen=True, slots=True)
class ListedPlace:
    """One place on an activation's place list, as it is built (ADR-0350 §5:10-§5:12).

    Planning shows each under its channel's heading, by a place label of its own
    (``L1``…), with its description and whether its task suggests it; a heading is
    never named (§5:13).

    Attributes:
        channel: The place's channel identity, whose place this is.
        heading: The heading of the channel it is listed under, for reading only.
        description: What the place is (§5:12).
        suggested: Whether its task suggests it (§5:11).
    """

    channel: ChannelIdentity
    heading: str
    description: str
    suggested: bool = False

    @property
    def place(self) -> str:
        """The place, as a message's effect record names it."""
        return place_of(self.channel)


# --- the spawner ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Spawner:
    """What the phases know of the activation calling a spawn, a cancel or a list pull.

    Attributes:
        activation_id: The calling activation, which a task it spawns names as its
            parent (§3:6).
        person: The person it is for, whom every task it spawns is for (§3:5).
        users_authority: Whether its input carries the person's authority, so a task it
            spawns is the person's (§3:7) and it may cancel or replace any of the
            person's tasks (§4:4).
        set_in: The place of its input, where a task it spawns is set (§3:6, §3:10).
        places: The places on its place list as last shown, by place: the only places
            a spawn may suggest (§5:6).
        carried: For an activation the Task Scheduler started, its own task's suggested
            places, which a spawn stating none carries forward (§5:6); empty otherwise.
        read_outside_content: Whether it has read outside content, so a task it spawns
            carries the outside-content mark (§3:8).
        supply: Its audience posture, which the list pull's running and ended
            activations are admitted under (ADR-0332 §4:2).
        sees_running: Whether its input's author is established, the one viewer
            ADR-0332 §4:3 shows running work to.
    """

    activation_id: str
    person: str
    users_authority: bool
    set_in: ChannelIdentity
    places: tuple[str, ...] = ()
    carried: tuple[str, ...] = ()
    read_outside_content: bool = False
    supply: TurnSupply | None = None
    sees_running: bool = False

    @property
    def author(self) -> ScheduledTaskAuthor:
        """Who a task it spawns is authored by (§3:7): the person, or the assistant."""
        return ScheduledTaskAuthor.PERSON if self.users_authority else ScheduledTaskAuthor.ASSISTANT


#: The activation whose round's calls are running, by what the runner needs of it.
_SPAWNING: Final[contextvars.ContextVar[Spawner | None]] = contextvars.ContextVar(
    "task_scheduler_spawning", default=None
)


@contextlib.contextmanager
def spawning(spawner: Spawner | None) -> Iterator[None]:
    """Hand ``spawner`` to the Task Scheduler's calls run inside this scope.

    The phases open it around acting for a round of an activation offered spawn (§3:4),
    so a spawn, a cancel and a list pull read who is calling from it and from nothing a
    call carries.

    Yields:
        Nothing: the scope is the context it runs in.
    """
    token = _SPAWNING.set(spawner)
    try:
        yield
    finally:
        _SPAWNING.reset(token)


def current_spawner() -> Spawner | None:
    """The spawner :func:`spawning` holds, or ``None`` outside such a scope."""
    return _SPAWNING.get()


# --- the listing (ADR-0350 §4:6-§4:8) ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaskEntry:
    """One scheduled task, as the list pull, a spawn and a cancel answer it.

    Attributes:
        task_id: The task, which planning names by its ``T`` label (§9:2).
        state: Its occurrence's state: pending, pushed, or how it ended.
        falls_due: The hub's rendering of when it falls due, from the record (§4:8).
        waits_on: The tasks it waits on, where its when is named tasks ending (§5:4).
        instruction: What it carries, or ``None`` where it carries the outside-content
            mark, whose text is withheld (§4:7).
        outside: Whether it carries the outside-content mark.
        places: The places it suggests, by place.
        parent: The activation that spawned it, which planning names by its episode's
            ``E`` label, so tasks spawned together read together (§4:6).
        parent_text: The hub's short description of that parent, from the record.
        author: Who set it: the person or the assistant.
        repeats: For a task with a rule, its rule in words (ADR-0340 §8:2); ``None``
            for any other.
        read_back: For the task a spawn wrote, the hub's read-back of it (ADR-0340
            §6:2); ``None`` in every other listing.
    """

    task_id: str
    state: str
    falls_due: str
    instruction: str | None
    outside: bool
    places: tuple[str, ...]
    parent: str
    parent_text: str
    author: str
    waits_on: tuple[str, ...] = ()
    repeats: str | None = None
    read_back: str | None = None


@dataclass(frozen=True, slots=True)
class ActivationEntry:
    """One activation the list pull shows: running, or one the Task Scheduler ran.

    Attributes:
        activation_id: The activation, which planning names by its episode's ``E`` label.
        started: When it started, in local time.
        place: The place it was started from, described.
        status: ``running``, or how it ended.
        input: Its input in brief, or ``None`` where it is withheld: an outside one, with
            its mark shown (§4:7), or a scheduled task's own instruction.
        outside: Whether any input it holds is outside, read with its relay mark
            (ADR-0351 §5:1, §5:7, §8:5).
        acted: For a running one, whether it has acted (ADR-0349 §5:6, §6:2).
        assistants: Whether its input is the assistant's (ADR-0351 §5:2), which says
            why a withheld input that is not outside is withheld.
        wrote_into: For an ended one, the places its messages were written into, as
            their effect records name them (ADR-0350 §12:8), each once; empty where it
            wrote none. ``None`` for a running one, and where the records could not be
            read, so nothing is said of where it spoke.
        may_have_written_into: For an ended one, the places a message of its may have
            gone into, whose outcome is not known; empty where none.
    """

    activation_id: str
    started: str
    place: str
    status: str
    input: str | None
    outside: bool
    acted: bool = False
    assistants: bool = False
    wrote_into: tuple[str, ...] | None = None
    may_have_written_into: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskListing:
    """What a call on the Task Scheduler came back with, for planning.

    Attributes:
        running: The activations running for the person, other than the asker (§4:6).
        scheduled: The person's pending scheduled tasks, each with its parent (§4:6).
        recent: The activations the Task Scheduler started for them that ended most
            recently (§4:6, §7:9).
        spawned: The task a spawn wrote, with the hub's rendering of when it falls due
            and of the places it suggests (§4:8).
        cancelled: The task a cancel ended what was pending of.
        listed: Whether it answers a list pull, whose three parts are shown even empty.
    """

    running: tuple[ActivationEntry, ...] = ()
    scheduled: tuple[TaskEntry, ...] = ()
    recent: tuple[ActivationEntry, ...] = ()
    spawned: TaskEntry | None = None
    cancelled: TaskEntry | None = None
    listed: bool = False


@dataclass(frozen=True, slots=True)
class StartingEntry:
    """An activation pushed from a task and not yet admitted (ADR-0352 §3:4).

    It has no episode yet, so it is shown under its task's ``T`` label, as starting.

    Attributes:
        task_id: The task whose occurrence was pushed to it.
    """

    task_id: str


@dataclass(frozen=True, slots=True)
class StillLive:
    """What an activation set up that is still live below it (ADR-0352 §3:1-§3:6).

    The stop call's result shows it beside the stopped activation's finished work. *Below*
    is the tasks the activation spawned, and the tasks those tasks' activations spawned in
    turn, whether or not those activations have ended (§3:2).

    Attributes:
        tasks: Each task below it with an occurrence pending, in the order written, at
            most the listing bound of them (§3:3, §3:6).
        more_tasks: How many more such tasks there are than ``tasks`` shows.
        activations: Each activation running or pushed from a task below it, oldest
            first, at most the listing bound of them: a running one as the list pull's
            running part shows it, one pushed and not yet admitted as starting (§3:4).
        more_activations: How many more such activations there are than are shown.
        read: Whether what is below could be read; where it could not, nothing else
            here says anything, since the stop itself was made.
    """

    tasks: tuple[TaskEntry, ...] = ()
    more_tasks: int = 0
    activations: tuple[ActivationEntry | StartingEntry, ...] = ()
    more_activations: int = 0
    read: bool = True

    @property
    def nothing(self) -> bool:
        """Whether nothing it set up is still live, as far as it was read (§3:1)."""
        return (
            self.read
            and not self.tasks
            and not self.activations
            and not self.more_tasks
            and not self.more_activations
        )

    @property
    def running(self) -> tuple[str, ...]:
        """Each activation it shows as running, which counts as shown running (§3:7)."""
        return tuple(
            one.activation_id for one in self.activations if isinstance(one, ActivationEntry)
        )


_LISTING_KIND: Final = "task_scheduler_listing"


def _task_json(entry: TaskEntry) -> dict[str, FrozenJson]:
    return {
        "task_id": entry.task_id,
        "state": entry.state,
        "falls_due": entry.falls_due,
        "waits_on": list(entry.waits_on),
        "instruction": entry.instruction,
        "outside": entry.outside,
        "places": list(entry.places),
        "parent": entry.parent,
        "parent_text": entry.parent_text,
        "author": entry.author,
        "repeats": entry.repeats,
        "read_back": entry.read_back,
    }


def _activation_json(entry: ActivationEntry) -> dict[str, FrozenJson]:
    return {
        "activation_id": entry.activation_id,
        "started": entry.started,
        "place": entry.place,
        "status": entry.status,
        "input": entry.input,
        "outside": entry.outside,
        "acted": entry.acted,
        "assistants": entry.assistants,
        "wrote_into": None if entry.wrote_into is None else list(entry.wrote_into),
        "may_have_written_into": list(entry.may_have_written_into),
    }


def encode_listing(listing: TaskListing) -> FrozenJson:
    """``listing`` as a call's result, which :func:`decode_listing` reads back."""
    return {
        "kind": _LISTING_KIND,
        "listed": listing.listed,
        "running": [_activation_json(one) for one in listing.running],
        "scheduled": [_task_json(one) for one in listing.scheduled],
        "recent": [_activation_json(one) for one in listing.recent],
        "spawned": None if listing.spawned is None else _task_json(listing.spawned),
        "cancelled": None if listing.cancelled is None else _task_json(listing.cancelled),
    }


def _str(held: Mapping[str, object], key: str) -> str:
    value = held[key]
    if not isinstance(value, str):
        msg = f"a listing's {key} is text"
        raise TypeError(msg)
    return value


def _strs(held: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = held[key]
    if not isinstance(value, list | tuple) or not all(isinstance(one, str) for one in value):
        msg = f"a listing's {key} is a list of text"
        raise TypeError(msg)
    return tuple(cast("list[str]", list(value)))


def _optional_str(held: Mapping[str, object], key: str) -> str | None:
    value = held[key]
    return None if value is None else _str(held, key)


def _later_str(held: Mapping[str, object], key: str) -> str | None:
    """A key added after a listing may have been recorded, which reads as ``None``."""
    return _optional_str(held, key) if key in held else None


def _task_of(value: object) -> TaskEntry:
    held = cast("Mapping[str, object]", value)
    return TaskEntry(
        task_id=_str(held, "task_id"),
        state=_str(held, "state"),
        falls_due=_str(held, "falls_due"),
        waits_on=_strs(held, "waits_on"),
        instruction=_optional_str(held, "instruction"),
        outside=bool(held["outside"]),
        places=_strs(held, "places"),
        parent=_str(held, "parent"),
        parent_text=_str(held, "parent_text"),
        author=_str(held, "author"),
        repeats=_later_str(held, "repeats"),
        read_back=_later_str(held, "read_back"),
    )


def _activation_of(value: object) -> ActivationEntry:
    held = cast("Mapping[str, object]", value)
    return ActivationEntry(
        activation_id=_str(held, "activation_id"),
        started=_str(held, "started"),
        place=_str(held, "place"),
        status=_str(held, "status"),
        input=_optional_str(held, "input"),
        outside=bool(held["outside"]),
        acted=bool(held.get("acted", False)),
        assistants=_assistants(held),
        wrote_into=(None if held.get("wrote_into") is None else _strs(held, "wrote_into")),
        may_have_written_into=(
            _strs(held, "may_have_written_into") if "may_have_written_into" in held else ()
        ),
    )


#: What a listing recorded before ADR-0351 §8:1 named its entry's origin by, and whether
#: each named the assistant's input.
_RECORDED_ORIGINS: Final = {"user": False, "outside": False, "assistant": True}


def _assistants(held: Mapping[str, object]) -> bool:
    """Whether an entry's input is the assistant's, a key added after a listing may have been.

    A listing recorded before it named the entry's origin instead, ``assistant`` for the
    assistant's input, and before that nothing, which reads as not the assistant's. A
    value neither key admits is no listing.
    """
    if "assistants" in held:
        value = held["assistants"]
        if not isinstance(value, bool):
            msg = "a listing's assistants is a flag"
            raise TypeError(msg)
        return value
    recorded = held.get("origin")
    if recorded is None:
        return False
    if not isinstance(recorded, str) or recorded not in _RECORDED_ORIGINS:
        msg = "a listing's origin is one it recorded"
        raise ValueError(msg)
    return _RECORDED_ORIGINS[recorded]


def decode_listing(output: FrozenJsonValue) -> TaskListing | None:
    """The listing a call on the Task Scheduler returned, or ``None`` where it is none.

    Args:
        output: A done call's result.

    Returns:
        The listing, or ``None`` where ``output`` is not one :func:`encode_listing` wrote.
    """
    if not isinstance(output, Mapping) or output.get("kind") != _LISTING_KIND:
        return None
    try:
        held = cast("Mapping[str, object]", output)
        spawned = held["spawned"]
        cancelled = held["cancelled"]
        return TaskListing(
            running=tuple(_activation_of(one) for one in cast("list[object]", held["running"])),
            scheduled=tuple(_task_of(one) for one in cast("list[object]", held["scheduled"])),
            recent=tuple(_activation_of(one) for one in cast("list[object]", held["recent"])),
            spawned=None if spawned is None else _task_of(spawned),
            cancelled=None if cancelled is None else _task_of(cancelled),
            listed=bool(held["listed"]),
        )
    except KeyError, TypeError, AttributeError, ValueError:
        return None


# --- the hub's renderings ----------------------------------------------------------------


def local_time(instant: datetime, zone: ZoneInfo) -> str:
    """``instant`` in ``zone``, to the minute, with its weekday and its zone's name."""
    local = instant.astimezone(zone)
    return f"{local:%a %d %b %Y %H:%M} ({zone.key})"


def shown_occurrence(task: ScheduledTask) -> ScheduledOccurrence:
    """The occurrence a rendering of ``task`` gives: its next, or the one that stands.

    A one-off task's one occurrence. For a task with a rule (ADR-0340 §4:6), the earliest
    still pending, its next; where none is, one running; otherwise its last.
    """
    occurrences = task.occurrences
    pending = [one for one in occurrences if one.state is OccurrenceState.PENDING]
    if pending:
        return min(pending, key=lambda one: (one.due_at is None, one.due_at, one.number))
    running = [one for one in occurrences if one.state is OccurrenceState.PUSHED]
    return running[-1] if running else occurrences[-1]


def when_text(task: ScheduledTask, zone: ZoneInfo, *, now: datetime) -> str:
    """The hub's rendering of when ``task`` falls due, from its record (ADR-0350 §4:8).

    In the person's zone ``zone``, or a rule's own where it names one (ADR-0340 §6:1);
    for a rule, its next occurrence, or that nothing more of it is pending (§8:2).
    """
    shown = task_zone(task, zone)
    when = task.when
    if isinstance(when, DueNow):
        return f"now: set to start at once, {local_time(task.set_at, shown)}"
    if isinstance(when, DueAt):
        return f"at {local_time(when.at, shown)}"
    occurrence = shown_occurrence(task)
    if isinstance(when, DueOnRule):
        words = rule_text(when, today=now.astimezone(shown).date(), zone=shown)
        if occurrence.state is not OccurrenceState.PENDING or occurrence.due_at is None:
            return f"{words}; nothing more of it is pending"
        next_at = occurrence.due_at
        return f"{words}; next at {local_time(next_at, shown)}{_elsewhere(when, next_at, shown)}"
    due = occurrence.due_at
    if due is not None:
        return f"once the tasks it waits on ended, at {local_time(due, shown)}"
    return "once every task it waits on has ended"


def _elsewhere(rule: DueOnRule, due_at: datetime, zone: ZoneInfo) -> str:
    """What a rendering of a rule's occurrence adds where another zone computed it.

    ADR-0340 §4:3: an occurrence pending when the person's zone changed keeps its
    instant, so it comes at the rule's time in the zone it was computed in, and the
    ones after it follow the person's zone now (#3451). Nothing where it did not.
    """
    if not computed_elsewhere(rule, due_at, zone):
        return ""
    clock = clock_text(rule.time_of_day)
    return (
        f", computed while the person's zone was an earlier one, so this one comes at "
        f"{clock} in that zone, and the ones after it at {clock} in {zone.key}"
    )


#: Past this local hour, a time today is said to fall tonight.
_EVENING: Final = 18


def _moment(instant: datetime, zone: ZoneInfo, *, now: datetime, named: bool) -> str:
    """An instant as the read-back says it: ``Tonight, Tuesday 21 October, at 8:00 PM``.

    With a relative word where it falls today or tomorrow, in ``zone``, and the zone's
    name where ``named``, for a rule naming its zone (ADR-0340 §6:1).
    """
    local = instant.astimezone(zone)
    today = now.astimezone(zone).date()
    day = local.date()
    told = f"{day_text(day, today=today)}, at {clock_text(local.time())}"
    if named:
        told += f" {zone.key} time"
    if day == today:
        return f"{'Tonight' if local.hour >= _EVENING else 'Today'}, {told}"
    if day == today + timedelta(days=1):
        return f"Tomorrow, {told}"
    return told


def _place_said(channel: ChannelIdentity, here: ChannelIdentity) -> str:
    """A suggested place as the read-back says it, with where it was set as *here*."""
    if channel == here:
        return "here"
    if channel.channel_type == "telegram":
        return "on Telegram"
    if channel.channel_type == "conversation":
        return "in another conversation in the hub's chat"
    return f"in {place_description(channel)}"


def read_back(task: ScheduledTask, zone: ZoneInfo, *, now: datetime, line: bool) -> str:
    """The read-back: the hub's rendering of the task a spawn wrote, from the record.

    ADR-0340 §6:2. The next occurrence's weekday, date and local time, with a relative
    word where it falls today or tomorrow; for a task waiting on named tasks, that it
    falls due when they end, and no time; for a rule, the rule in words with its from
    and until; and each place it suggests, the place it was set in as *here*, or that it
    suggests none, adding, where ``line`` says the line is connected, that it may still
    message the person there.

    Args:
        task: The task as written.
        zone: The person's zone; a rule naming a zone is said in its own.
        now: The instant it is said at, from which today and tomorrow are read.
        line: Whether the line's chat is on the spawner's place list, so connected.
    """
    shown = task_zone(task, zone)
    when = task.when
    occurrence = shown_occurrence(task)
    due = occurrence.due_at
    if isinstance(when, DueAfterTasks):
        said = (
            "When the tasks it waits on have all ended"
            if due is None
            else "Now, since the tasks it waits on have all ended"
        )
    elif isinstance(when, DueNow) or due is None or due <= now:
        said = "Now"
    else:
        said = _moment(due, shown, now=now, named=isinstance(when, DueOnRule) and bool(when.zone))
    if isinstance(when, DueOnRule):
        words = rule_text(when, today=now.astimezone(shown).date(), zone=shown)
        if due is not None:
            said += _elsewhere(when, due, shown)
        said = f"{words[:1].upper()}{words[1:]}; next: {said}"
    if task.places:
        places = " and ".join(_place_said(one, task.set_in) for one in task.places)
        return f"{said}, {places}."
    if line:
        return f"{said}. It suggests no place, and may still message the person on Telegram."
    return f"{said}. It suggests no place."


#: Each place's kind, described for reading (§5:12).
_PLACE_DESCRIPTIONS: Final = {
    "conversation": "a conversation in the hub's chat",
    "telegram": "the person's Telegram chat with their assistant",
    TASK_SCHEDULER: "a scheduled step, started by the Task Scheduler",
    # ADR-0362 §3:4: a ticket's spawn runs in the approval's own activation too.
    APPROVALS: "the approvals, where the person answered a request for their yes",
    "informational_event": "an event a source reported",
}


def place_description(channel: ChannelIdentity | None) -> str:
    """A place, described for reading: what it is, never what it can do (§5:12)."""
    if channel is None:
        return "no place"
    kind = channel.channel_type
    return _PLACE_DESCRIPTIONS.get(kind, f"a place of the {kind} channel")


#: How an occurrence's state reads to planning.
_STATE_TEXT: Final = {
    OccurrenceState.PENDING: "pending",
    OccurrenceState.PUSHED: "running, or about to start",
    OccurrenceState.DONE: "done",
    OccurrenceState.COULDNT_FINISH: "couldn't finish",
    OccurrenceState.STOPPED: "stopped",
    OccurrenceState.INTERRUPTED: "interrupted",
    OccurrenceState.CANCELLED: "cancelled",
    OccurrenceState.SKIPPED: "skipped",
}


def outcome_text(occurrence: ScheduledOccurrence) -> str:
    """How an occurrence stands, in words."""
    return _STATE_TEXT[occurrence.state]


def occurrence_outcome(episode: EpisodicMemory) -> OccurrenceState | None:
    """The outcome an occurrence takes from how its activation's episode froze (§7:6).

    *done* where it froze completed; *couldn't finish* where it froze failed; *stopped*
    where a stop ended it; and *interrupted* for every other ending. ``None`` for the
    restart's close (ADR-0286 §7:2), which §8 settles, and for an episode still open.
    """
    processing = episode.processing_record
    if processing is None or processing.status is None:
        return None
    if processing.reason is ProcessingReason.HUB_STOPPED:
        return None
    if processing.status is ProcessingStatus.COMPLETED:
        return OccurrenceState.DONE
    if processing.status is ProcessingStatus.FAILED:
        return OccurrenceState.COULDNT_FINISH
    if processing.reason is ProcessingReason.STOPPED:
        return OccurrenceState.STOPPED
    return OccurrenceState.INTERRUPTED


#: How much of a text a lineage step or a start shows of it.
_STEP_CHARS: Final = 160


def _brief(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _STEP_CHARS else f"{flat[: _STEP_CHARS - 1]}…"


def task_input(  # noqa: PLR0913 — the task, the occurrence's two facts, the zone, and the three the push decides
    task: ScheduledTask,
    *,
    due_at: datetime | None,
    second_try: bool,
    zone: ZoneInfo,
    late_at: datetime | None,
    skipped: int = 0,
    now: datetime | None = None,
) -> str:
    """The input an occurrence's activation is given, stated by the hub (ADR-0350 §6:2).

    What the task carries, the creator's instruction as planning wrote it (§6:3); when
    and where it was set; the instant it was due; and whether it is late (§8:9) or a
    second try (§8:6). For a task with a rule, its rule in words and how many
    occurrences it skipped, where it skipped any (ADR-0340 §7:1). Whether and how its
    messages mention any of it is the activation's judgment (ADR-0340 §7:2).

    Args:
        task: The task.
        due_at: The instant the occurrence pushed was due.
        second_try: Whether it is pushed again as a second try.
        zone: The person's zone, which local times are told in; a rule naming a zone
            is told in its own (ADR-0340 §6:1).
        late_at: When it was pushed, where that was past the lateness grace; ``None``
            where it is not late.
        skipped: How many earlier occurrences of its rule were recorded skipped as it
            was pushed (ADR-0340 §4:8).
        now: The instant it is told at, from which a rule's from is read; the due
            instant where ``None``.
    """
    shown = task_zone(task, zone)
    who = "the person" if task.author is ScheduledTaskAuthor.PERSON else "the assistant"
    facts = [
        f"set by {who} in {place_description(task.set_in)}, {local_time(task.set_at, shown)}",
    ]
    rule = task.when if isinstance(task.when, DueOnRule) else None
    if rule is not None:
        told = now or due_at or task.set_at
        facts.append(
            f"it repeats {rule_text(rule, today=told.astimezone(shown).date(), zone=shown)}"
        )
    if due_at is not None:
        elsewhere = "" if rule is None else _elsewhere(rule, due_at, shown)
        facts.append(f"due {local_time(due_at, shown)}{elsewhere}")
    if skipped:
        missed = "occurrence" if skipped == 1 else "occurrences"
        facts.append(f"it skipped {skipped} earlier {missed}, missed while it was not pushed")
    if late_at is not None:
        facts.append(f"late: it was started only {local_time(late_at, shown)}")
    if second_try:
        facts.append(
            "a second try: a run cut off by a restart may already have sent its message, "
            "and whether it arrived is not known"
        )
    return f"{task.instruction}\n\n(A scheduled task: {'; '.join(facts)}.)"


@dataclass(frozen=True, slots=True)
class LineageStep:
    """One line of the schedule's place window, a task's lineage (ADR-0350 §6:5).

    Attributes:
        text: The line, as the hub states it from the tasks it keeps.
        episode_id: The episode of the activation the line gives, where it is frozen.
        current: Whether it is the current activation's step.
        at: When it ran, or began.
    """

    text: str
    episode_id: str | None = None
    current: bool = False
    at: datetime | None = None


def _frozen(episodes: Mapping[str, EpisodicMemory], activation_id: str) -> EpisodicMemory | None:
    record = episodes.get(f"activation:{activation_id}")
    processing = None if record is None else record.processing_record
    return None if processing is None or processing.is_open else record


def lineage_occurrence(task: ScheduledTask, below: ScheduledTask) -> ScheduledOccurrence:
    """The occurrence of ``task`` whose activation spawned ``below``, its next step.

    A one-off task's one occurrence; for a task with a rule, the one of its occurrences
    pushed to ``below``'s parent (ADR-0340 §4:10), or its first where none names it.
    """
    return next(
        (one for one in task.occurrences if below.parent in one.activations),
        task.occurrences[0],
    )


def lineage_steps(
    lineage: Sequence[ScheduledTask],
    episodes: Mapping[str, EpisodicMemory],
    zone: ZoneInfo,
) -> tuple[LineageStep, ...]:
    """The schedule's window: a task's lineage as steps numbered from the start (§6:5).

    A *start* line, giving the activation that began the lineage, which is not a task,
    by its place, its local time and its input in brief, with its episode's link; then
    each ancestor step in order, when it ran, its outcome and its instruction in one
    line; then the current activation, marked as current. A text resting on outside
    content is withheld, its mark shown. An episode still open is never linked.

    Args:
        lineage: The current task last, and each task above it before it.
        episodes: The lineage's activations' episodes, by address, as read.
        zone: The person's zone, which local times are told in; a step with a rule
            naming a zone is told in its own (ADR-0340 §6:1).
    """
    if not lineage:
        return ()
    steps: list[LineageStep] = []
    start = _frozen(episodes, lineage[0].parent)
    processing = None if start is None else start.processing_record
    if processing is None:
        steps.append(LineageStep(text="Start: an activation whose episode is not to be read"))
    else:
        payload = getattr(processing.trigger.payload, "text", None)
        said = (
            "its input rests on outside content, and is not shown"
            if holds_outside(processing.trigger, processing.understanding, processing.joined)
            or not isinstance(payload, str)
            else _brief(payload)
        )
        steps.append(
            LineageStep(
                text=(
                    f"Start, in {place_description(processing.trigger.channel)}, "
                    f"{local_time(processing.started_at, zone)}: {said}"
                ),
                episode_id=start.id if start is not None else None,
                at=processing.started_at,
            )
        )
    for number, task in enumerate(lineage, 1):
        what = (
            "it carries outside content, which is not shown"
            if task.outside_content
            else _brief(task.instruction)
        )
        if number == len(lineage):
            steps.append(LineageStep(text=f"Step {number}, current: {what}", current=True))
            break
        occurrence = lineage_occurrence(task, lineage[number])
        ran = None if not occurrence.activations else _frozen(episodes, occurrence.activations[-1])
        record = None if ran is None else ran.processing_record
        when = occurrence.ended_at if record is None else record.started_at
        told = "" if when is None else f", {local_time(when, task_zone(task, zone))}"
        steps.append(
            LineageStep(
                text=f"Step {number}{told}, {outcome_text(occurrence)}: {what}",
                episode_id=None if ran is None else ran.id,
                at=when,
            )
        )
    return tuple(steps)
