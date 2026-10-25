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
  input a due occurrence's activation is given (§6:2) and of its lineage window (§6:5).

**Names** (§2:8): the channel is the *Task Scheduler* in full, its items *scheduled
tasks*; "the scheduler" stays ADR-0083 §7's housekeeping loop.
"""

from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

from ai_assistant.core.channel_validation import TASK_SCHEDULER
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
    Idempotency,
    InputOrigin,
    LabelKind,
    OccurrenceState,
    ProcessingReason,
    ProcessingStatus,
    Reversibility,
    RiskLevel,
    ScheduledTaskAuthor,
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

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
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
    "TaskEntry",
    "TaskListing",
    "current_spawner",
    "decode_listing",
    "encode_listing",
    "lineage_steps",
    "local_time",
    "occurrence_outcome",
    "outcome_text",
    "place_description",
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
        "activation of its own when it falls due, reading what it carries. Give at most "
        "one of at, delay_minutes and after; with none it falls due now."
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
                    "When it falls due: an ISO 8601 instant with its UTC offset, such as "
                    "2026-10-25T20:00:00-04:00."
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
    "Cancel what is still pending of a scheduled task. It stops nothing already running.",
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
        "and the scheduled work that ended most recently."
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


@dataclass(frozen=True, slots=True)
class ActivationEntry:
    """One activation the list pull shows: running, or one the Task Scheduler ran.

    Attributes:
        activation_id: The activation, which planning names by its episode's ``E`` label.
        started: When it started, in local time.
        place: The place it was started from, described.
        status: ``running``, or how it ended.
        input: Its input in brief, or ``None`` where it rests on outside content, whose
            text is withheld with its mark shown (§4:7).
        outside: Whether its input's origin is outside.
    """

    activation_id: str
    started: str
    place: str
    status: str
    input: str | None
    outside: bool


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
    }


def _activation_json(entry: ActivationEntry) -> dict[str, FrozenJson]:
    return {
        "activation_id": entry.activation_id,
        "started": entry.started,
        "place": entry.place,
        "status": entry.status,
        "input": entry.input,
        "outside": entry.outside,
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
    )


def decode_listing(output: FrozenJsonValue) -> TaskListing | None:
    """The listing a call on the Task Scheduler returned, or ``None`` where it is none.

    Args:
        output: A done call's result.

    Returns:
        The listing, or ``None`` where ``output`` is not one :func:`encode_listing` wrote.
    """
    if not isinstance(output, dict) or output.get("kind") != _LISTING_KIND:
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
    except KeyError, TypeError, AttributeError:
        return None


# --- the hub's renderings ----------------------------------------------------------------


def local_time(instant: datetime, zone: ZoneInfo) -> str:
    """``instant`` in ``zone``, to the minute, with its weekday and its zone's name."""
    local = instant.astimezone(zone)
    return f"{local:%a %d %b %Y %H:%M} ({zone.key})"


def when_text(task: ScheduledTask, zone: ZoneInfo) -> str:
    """The hub's rendering of when ``task`` falls due, from its record (ADR-0350 §4:8)."""
    when = task.when
    if isinstance(when, DueNow):
        return f"now: set to start at once, {local_time(task.set_at, zone)}"
    if isinstance(when, DueAt):
        return f"at {local_time(when.at, zone)}"
    assert isinstance(when, DueAfterTasks)  # noqa: S101 — the when's three members
    due = task.occurrences[0].due_at
    if due is not None:
        return f"once the tasks it waits on ended, at {local_time(due, zone)}"
    return "once every task it waits on has ended"


def place_description(channel: ChannelIdentity | None) -> str:
    """A place, described for reading: what it is, never what it can do (§5:12)."""
    if channel is None:
        return "no place"
    kind = channel.channel_type
    if kind == "conversation":
        return "a conversation in the hub's chat"
    if kind == "telegram":
        return "the person's Telegram chat with their assistant"
    if kind == TASK_SCHEDULER:
        return "a scheduled step, started by the Task Scheduler"
    if kind == "informational_event":
        return "an event a source reported"
    return f"a place of the {kind} channel"


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


def task_input(
    task: ScheduledTask,
    occurrence: ScheduledOccurrence,
    zone: ZoneInfo,
    *,
    late_at: datetime | None,
) -> str:
    """The input an occurrence's activation is given, stated by the hub (ADR-0350 §6:2).

    What the task carries, the creator's instruction as planning wrote it (§6:3); when
    and where it was set; the instant it was due; and whether it is late (§8:9) or a
    second try (§8:6). Whether and how its messages mention either is the activation's
    judgment.

    Args:
        task: The task.
        occurrence: The occurrence pushed.
        zone: The zone local times are told in.
        late_at: When it was pushed, where that was past the lateness grace; ``None``
            where it is not late.
    """
    who = "the person" if task.author is ScheduledTaskAuthor.PERSON else "the assistant"
    facts = [
        f"set by {who} in {place_description(task.set_in)}, {local_time(task.set_at, zone)}",
    ]
    if occurrence.due_at is not None:
        facts.append(f"due {local_time(occurrence.due_at, zone)}")
    if late_at is not None:
        facts.append(f"late: it was started only {local_time(late_at, zone)}")
    if occurrence.second_try:
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
        zone: The zone local times are told in.
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
            if processing.trigger.origin is InputOrigin.OUTSIDE or not isinstance(payload, str)
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
        occurrence = task.occurrences[0]
        ran = None if not occurrence.activations else _frozen(episodes, occurrence.activations[-1])
        record = None if ran is None else ran.processing_record
        when = occurrence.ended_at if record is None else record.started_at
        told = "" if when is None else f", {local_time(when, zone)}"
        steps.append(
            LineageStep(
                text=f"Step {number}{told}, {outcome_text(occurrence)}: {what}",
                episode_id=None if ran is None else ran.id,
                at=when,
            )
        )
    return tuple(steps)
