"""The Task Scheduler's scheduled tasks: every rule the plan store decides, stated once.

ADR-0350 puts the Task Scheduler's content in the plan store, because a task, the spawn's
effect claim and the stop that refuses it are decided in one step (§3:3), and §12:3
lists what the store decides of them: the write with its replace and its limits (§9:4,
§9:7-§9:9), the cancel (§9:5), the push (§7:5), an occurrence's outcome (§7:6, §8), and
the removal once nothing of a task or below it is live (§7:8). No push is refused below a
stopped activation (ADR-0352 §2:3); what is left of the cascade record is the SQLite
store's upgrade that retires it, decided here too (:func:`decide_cascade_retirement`,
ADR-0352 §2:6).
The decisions are written here rather than in each store, as
:mod:`ai_assistant.planning.activation_effects` writes the claim's, because two
statements of one rule are two places for it to drift. Each store's job is the
indivisible step the decision is taken inside: it reads the whole schedule into a
:class:`Schedule`, runs one decision over it, and writes back what the decision changed.

**The whole schedule is read at every step.** It is small by construction: §12:5's
pending limit bounds each person's pending work, and §7:8 removes a task once nothing of
it or below it is live, so what a store holds is that work and its live ancestors.

The canonical fake in :mod:`ai_assistant.testing` re-implements this rather than
importing it, for the reason the claim's module gives.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    PUSHED_OUTCOMES,
    ActivationEffect,
    DueAfterTasks,
    DueAt,
    DueNow,
    DueOccurrence,
    DueOnRule,
    Identifier,
    NonBlankEncodableText,
    OccurrencePush,
    OccurrenceState,
    RulePush,
    ScheduledDue,
    ScheduledOccurrence,
    ScheduledTask,
    ScheduledTaskAuthor,
    ScheduledTaskCancel,
    ScheduledTaskWrite,
    TaskRefusal,
    TaskSpawn,
    TaskWriteAnswer,
    UtcInstant,
    encodable_text,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator
    from datetime import datetime

_ID: Final[TypeAdapter[Identifier]] = TypeAdapter(Identifier)
_PERSON: Final[TypeAdapter[str]] = TypeAdapter(NonBlankEncodableText)
_INSTANT: Final[TypeAdapter[datetime]] = TypeAdapter(UtcInstant)

#: The bound a limit, an occurrence number and a count are read below.
_INT_BOUND: Final = 2**31


@dataclass(slots=True)
class Schedule:
    """The Task Scheduler's content as one store step reads it, and what it changed.

    Attributes:
        tasks: Every task the store holds, by id, in the order written. A decision
            replaces an entry rather than mutating the frozen record.
        now: The store's clock, read once for the step: when an occurrence ends.
        changed: The ids of the tasks the step wrote, new or rewritten, in order.
        removed: The ids of the tasks the step removed.
    """

    tasks: dict[str, ScheduledTask]
    now: datetime
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    def put(self, task: ScheduledTask) -> None:
        """Hold ``task`` under its id, new or replacing the record held, and note it."""
        self.tasks[task.id] = task
        if task.id not in self.changed:
            self.changed.append(task.id)


# --- what a caller hands in ------------------------------------------------------------


def checked_id(value: object, what: str) -> str:
    """Return ``value`` as the identifier it names, or refuse it.

    Args:
        value: What the caller passed.
        what: What the value names, for the message.

    Returns:
        The validated identifier.

    Raises:
        PlanningError: If the value is not an identifier.
    """
    try:
        return _ID.validate_python(value)
    except ValidationError as exc:
        msg = f"a {what} is named by an identifier, and {value!r} is not one"
        raise PlanningError(msg) from exc


def checked_optional_id(value: object, what: str) -> str | None:
    """:func:`checked_id`, admitting ``None``."""
    return None if value is None else checked_id(value, what)


def checked_person(value: object) -> str:
    """Return ``value`` as the person a task is for, or refuse it.

    Raises:
        PlanningError: If it is blank or has no UTF-8 encoding.
    """
    try:
        return _PERSON.validate_python(value, strict=True)
    except ValidationError as exc:
        msg = f"a scheduled task is for a person, named by non-blank text, not {value!r}"
        raise PlanningError(msg) from exc


def checked_limit(value: object, what: str) -> int:
    """Return ``value`` as a positive integer limit, or refuse it (ADR-0350 §12:5).

    Raises:
        PlanningError: If it is not an ``int``, is a ``bool``, or is not at least one.
    """
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value < _INT_BOUND:
        msg = f"the {what} is a positive integer, not {value!r}"
        raise PlanningError(msg)
    return value


def checked_number(value: object) -> int:
    """Return ``value`` as an occurrence's number, or refuse it.

    Raises:
        PlanningError: If it is not a positive ``int``.
    """
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value < _INT_BOUND:
        msg = f"an occurrence is numbered by a positive integer, not {value!r}"
        raise PlanningError(msg)
    return value


def checked_instant(value: object) -> datetime:
    """Return ``value`` as a timezone-aware instant, or refuse it.

    Raises:
        PlanningError: If it is not a timezone-aware ``datetime``.
    """
    try:
        return _INSTANT.validate_python(value, strict=True)
    except ValidationError as exc:
        msg = f"the Task Scheduler compares timezone-aware instants, not {value!r}"
        raise PlanningError(msg) from exc


def checked_spawn(spawn: object) -> TaskSpawn:
    """Return the store's own copy of a spawn, or refuse it (ADR-0350 §3:6).

    Rebuilt through validation, so a caller that mutates its value after the call
    cannot change what the store writes.

    Raises:
        PlanningError: If it is not a valid ``TaskSpawn``.
    """
    if not isinstance(spawn, TaskSpawn):
        msg = f"a scheduled task is written from a TaskSpawn, not {type(spawn).__name__}"
        raise PlanningError(msg)
    try:
        return TaskSpawn.model_validate(spawn.model_dump())
    except ValidationError as exc:
        msg = f"the spawn to write does not validate: {exc}"
        raise PlanningError(msg) from exc


def checked_rule_push(value: object) -> RulePush | None:
    """Return the store's own copy of a push's rule instants, or refuse them (ADR-0340 §9:3).

    Raises:
        PlanningError: If it is neither ``None`` nor a valid ``RulePush``.
    """
    if value is None:
        return None
    if not isinstance(value, RulePush):
        msg = f"a rule's push states its instants as a RulePush, not {type(value).__name__}"
        raise PlanningError(msg)
    try:
        return RulePush.model_validate(value.model_dump())
    except ValidationError as exc:
        msg = f"the rule's push does not validate: {exc}"
        raise PlanningError(msg) from exc


def checked_spawn_effect(effect: ActivationEffect) -> ActivationEffect:
    """Refuse a spawn's effect record that is not a call (ADR-0350 §3:3, §4:1).

    A spawn is a call to a capability, so its record is a call's, already revalidated
    as a claim by :func:`~ai_assistant.planning.activation_effects.revalidated_claim`.

    Raises:
        PlanningError: If the record is a message's.
    """
    if not effect.is_call:
        msg = f"a spawn's effect record is a call's, and {effect.id} is a message's"
        raise PlanningError(msg)
    return effect


def checked_state(value: object) -> OccurrenceState:
    """Return ``value`` as an occurrence state, or refuse it.

    Raises:
        PlanningError: If it is not an ``OccurrenceState``.
    """
    if not isinstance(value, OccurrenceState):
        msg = f"an occurrence's state is an OccurrenceState, not {value!r}"
        raise PlanningError(msg)
    return value


def requested_states(states: object) -> frozenset[OccurrenceState]:
    """Return the states a read names, or refuse them.

    Raises:
        PlanningError: If ``states`` is a string or not a sequence of states.
    """
    if (
        not isinstance(states, Sequence)
        or isinstance(states, (str, bytes))
        or not all(isinstance(one, OccurrenceState) for one in states)
    ):
        msg = "a read of scheduled tasks by state names a sequence of OccurrenceState values"
        raise PlanningError(msg)
    return frozenset(states)


def requested_ids(ids: object, what: str) -> tuple[str, ...]:
    """Return the ids a read names, each once in the order given, or refuse them.

    The same line :func:`~ai_assistant.planning.activation_effects.requested_activations`
    draws: a bare string, anything but a sequence, and an id with no UTF-8 encoding,
    which a SQLite store could not bind, are refused.

    Raises:
        PlanningError: If ``ids`` is a bare string, not a sequence of strings, or names
            an id with no UTF-8 encoding.
    """
    if (
        not isinstance(ids, Sequence)
        or isinstance(ids, (str, bytes))
        or not all(isinstance(one, str) for one in ids)
    ):
        msg = f"a read of {what} names a sequence of ids, not one string or anything else"
        raise PlanningError(msg)
    for index, one in enumerate(ids):
        try:
            encodable_text(one)
        except ValueError as exc:
            msg = f"a read of {what} names ids, and the one at index {index} is not: {exc}"
            raise PlanningError(msg) from exc
    return tuple(dict.fromkeys(ids))


# --- reading the schedule --------------------------------------------------------------


def task_of(tasks: dict[str, ScheduledTask], activation_id: str) -> ScheduledTask | None:
    """The task an occurrence of which was pushed to ``activation_id``, or ``None``."""
    return next((task for task in tasks.values() if activation_id in task.activations), None)


def lineage(tasks: dict[str, ScheduledTask], activation_id: str) -> tuple[ScheduledTask, ...]:
    """The lineage of the task pushed to ``activation_id``, from the start (§6:5).

    The task last, and each task above it before it: a task is above another where an
    occurrence of it was pushed to the other's parent. Empty where no task was pushed
    to the activation.
    """
    chain: list[ScheduledTask] = []
    current = task_of(tasks, activation_id)
    while current is not None and current not in chain:
        chain.append(current)
        current = task_of(tasks, current.parent)
    return tuple(reversed(chain))


def _above(tasks: dict[str, ScheduledTask], task: ScheduledTask) -> tuple[ScheduledTask, ...]:
    """``task`` and each task above it, from it upwards."""
    found: list[ScheduledTask] = []
    current: ScheduledTask | None = task
    while current is not None and current not in found:
        found.append(current)
        current = task_of(tasks, current.parent)
    return tuple(found)


def below(tasks: dict[str, ScheduledTask], task: ScheduledTask) -> Iterator[ScheduledTask]:
    """Every task below ``task``: spawned by its occurrences' activations, or theirs."""
    seen = {task.id}
    frontier = set(task.activations)
    while frontier:
        children = [one for one in tasks.values() if one.parent in frontier and one.id not in seen]
        frontier = set()
        for child in children:
            seen.add(child.id)
            frontier.update(child.activations)
            yield child


def _live(task: ScheduledTask) -> bool:
    """Whether something of ``task`` is pending or pushed."""
    return any(
        one.state in {OccurrenceState.PENDING, OccurrenceState.PUSHED} for one in task.occurrences
    )


def live_below(tasks: dict[str, ScheduledTask], task_id: str) -> bool:
    """Whether a task below the named one is pending or pushed (§7:8).

    A task the store does not hold has nothing below it.
    """
    task = tasks.get(task_id)
    return task is not None and any(_live(one) for one in below(tasks, task))


def by_person(
    tasks: dict[str, ScheduledTask], person: str, states: frozenset[OccurrenceState]
) -> tuple[ScheduledTask, ...]:
    """A person's tasks with an occurrence in any of ``states``, in write order."""
    return tuple(
        task
        for task in tasks.values()
        if task.person == person and any(one.state in states for one in task.occurrences)
    )


def spawned_by(
    tasks: dict[str, ScheduledTask], activations: Sequence[str]
) -> tuple[ScheduledTask, ...]:
    """The tasks whose parent is any of ``activations``, in write order."""
    named = set(activations)
    return tuple(task for task in tasks.values() if task.parent in named)


def due(tasks: dict[str, ScheduledTask], at: datetime) -> ScheduledDue:
    """The pending occurrences due at or before ``at``, and the next due after (§7:2-§7:4)."""
    found: list[tuple[datetime, int, DueOccurrence]] = []
    later: datetime | None = None
    for index, task in enumerate(tasks.values()):
        for one in task.occurrences:
            if one.state is not OccurrenceState.PENDING or one.due_at is None:
                continue
            if one.due_at <= at:
                found.append((one.due_at, index, DueOccurrence(task=task, number=one.number)))
            elif later is None or one.due_at < later:
                later = one.due_at
    found.sort(key=lambda item: (item[0], item[1], item[2].number))
    return ScheduledDue(due=tuple(item[2] for item in found), next_due_at=later)


# --- the steps -------------------------------------------------------------------------


def _rebuilt(task: ScheduledTask, occurrence: ScheduledOccurrence) -> ScheduledTask:
    """``task`` with ``occurrence`` in place of the one of its number, revalidated."""
    try:
        return ScheduledTask.model_validate(
            {
                **task.model_dump(),
                "occurrences": tuple(
                    occurrence if one.number == occurrence.number else one
                    for one in task.occurrences
                ),
            }
        )
    except ValidationError as exc:
        msg = f"scheduled task {task.id} would no longer validate: {exc}"
        raise PlanningError(msg) from exc


def _occurrence(occurrence: ScheduledOccurrence, **update: Any) -> ScheduledOccurrence:
    """``occurrence`` with ``update`` applied, revalidated."""
    try:
        return ScheduledOccurrence.model_validate({**occurrence.model_dump(), **update})
    except ValidationError as exc:
        msg = f"the occurrence would no longer validate: {exc}"
        raise PlanningError(msg) from exc


def _waits_ended(tasks: dict[str, ScheduledTask], when: DueAfterTasks) -> datetime | None:
    """The instant the last of the named tasks ended, where all have, or ``None`` (§5:4)."""
    named = [tasks.get(one) for one in when.tasks]
    ends = [None if task is None else task.ended_at for task in named]
    if any(end is None for end in ends):
        return None
    return max(end for end in ends if end is not None)


def _release(schedule: Schedule) -> None:
    """Set the due instant of every pending occurrence whose waits have all ended (§5:4).

    Run after every step that may end a task, so a task waiting on it falls due at the
    instant the last of what it waits for ended, and the sensor, woken by the write,
    finds it due (§7:7).
    """
    for task in list(schedule.tasks.values()):
        if not isinstance(task.when, DueAfterTasks):
            continue
        waiting = [
            one
            for one in task.occurrences
            if one.state is OccurrenceState.PENDING and one.due_at is None
        ]
        if not waiting:
            continue
        ended = _waits_ended(schedule.tasks, task.when)
        if ended is None:
            continue
        rebuilt = task
        for one in waiting:
            rebuilt = _rebuilt(rebuilt, _occurrence(one, due_at=ended))
        schedule.put(rebuilt)


def _cancel_pending(schedule: Schedule, task: ScheduledTask) -> ScheduledTask:
    """End every pending occurrence of ``task`` cancelled, now (§9:5)."""
    rebuilt = task
    for one in task.occurrences:
        if one.state is OccurrenceState.PENDING:
            rebuilt = _rebuilt(
                rebuilt, _occurrence(one, state=OccurrenceState.CANCELLED, ended_at=schedule.now)
            )
    schedule.put(rebuilt)
    return rebuilt


def _pending_count(tasks: dict[str, ScheduledTask], person: str) -> int:
    """How many pending occurrences the person's tasks hold (§9:8)."""
    return sum(
        1
        for task in tasks.values()
        if task.person == person
        for one in task.occurrences
        if one.state is OccurrenceState.PENDING
    )


def _refused(reason: TaskRefusal) -> ScheduledTaskWrite:
    return ScheduledTaskWrite(answer=TaskWriteAnswer.REFUSED, reason=reason)


def _replace_refusal(
    replaced: ScheduledTask | None, spawn: TaskSpawn, spawner: str, *, replace_any: bool
) -> TaskRefusal | None:
    """Why §9:4 does not allow the replace, if it does not."""
    if replaced is None:
        return TaskRefusal.UNKNOWN_TASK
    if replaced.person != spawn.person:
        return TaskRefusal.ANOTHER_PERSONS
    if not replace_any and replaced.parent != spawner:
        return TaskRefusal.NOT_ITS_SPAWN
    if not replaced.pending:
        return TaskRefusal.NOTHING_PENDING
    return None


def _wait_allowed(
    tasks: dict[str, ScheduledTask], spawn: TaskSpawn, replaced: ScheduledTask | None
) -> bool:
    """Whether the spawn's wait is one §5:4 and §9:4 allow.

    Every task it waits on is held, is for its person and is one-off, never one with a
    rule (§5:4, "it may name only one-off tasks"). And a replace never moves
    a task past its wait (§9:4, "a task waiting on named tasks is replaced only with a
    valid wait"; §5:4, "what it waits for never changes"): where the replaced task waits
    on tasks not all ended, the replacement waits too, on each of them that has not.
    """
    when = spawn.when
    if replaced is not None and isinstance(replaced.when, DueAfterTasks):
        unended = {
            one for one in replaced.when.tasks if (held := tasks.get(one)) is None or not held.ended
        }
        named = set(when.tasks) if isinstance(when, DueAfterTasks) else set()
        if not unended <= named:
            return False
    if not isinstance(when, DueAfterTasks):
        return True
    return all(
        (task := tasks.get(one)) is not None
        and task.person == spawn.person
        and not isinstance(task.when, DueOnRule)
        for one in when.tasks
    )


def decide_task_write(  # noqa: PLR0913 — the schedule, the spawn and its spawner, the replace's rule and the two limits
    schedule: Schedule,
    spawn: TaskSpawn,
    spawner: str,
    *,
    replace_any: bool,
    chain_limit: int,
    pending_limit: int,
) -> ScheduledTaskWrite:
    """Decide and apply one spawn's write, after its effect claim was decided (§3:3).

    The claim's own refusals are the caller's, decided first in the same step; this
    takes the rule's author (ADR-0340 §4:1, §9:2), the replace (§9:4), the wait (§5:4)
    and the two limits (§9:7-§9:8) in that order, and on a refusal changes nothing. A
    rule's first occurrence is written at the instant the spawn carries (ADR-0340 §4:5,
    §9:3), which the spawn's own validation requires for a rule and refuses for any
    other when; the store computes no instant (§9:5).

    Args:
        schedule: The schedule the step read.
        spawn: The revalidated spawn.
        spawner: The spawning activation, which the effect record names.
        replace_any: Whether the spawner may replace a task it did not spawn (§4:4).
        chain_limit: The chain limit.
        pending_limit: The pending limit.

    Returns:
        ``WRITTEN`` with the task, or ``REFUSED`` with its reason.

    Raises:
        PlanningError: If the store already holds a task under the spawn's id.
    """
    tasks = schedule.tasks
    if spawn.id in tasks:
        msg = f"the plan store already holds scheduled task {spawn.id} (ADR-0350 §3:3)"
        raise PlanningError(msg)
    if isinstance(spawn.when, DueOnRule) and spawn.author is not ScheduledTaskAuthor.PERSON:
        return _refused(TaskRefusal.ASSISTANTS_RULE)
    replaced = None if spawn.replaces is None else tasks.get(spawn.replaces)
    if spawn.replaces is not None:
        refusal = _replace_refusal(replaced, spawn, spawner, replace_any=replace_any)
        if refusal is not None:
            return _refused(refusal)
    if not _wait_allowed(tasks, spawn, replaced):
        return _refused(TaskRefusal.INVALID_WAIT)
    above = task_of(tasks, spawner)
    chain = (
        replaced.chain_length
        if replaced is not None
        else 1
        if above is None
        else above.chain_length + 1
    )
    if chain > chain_limit:
        return _refused(TaskRefusal.CHAIN_LIMIT)
    freed = (
        0
        if replaced is None
        else sum(1 for one in replaced.occurrences if one.state is OccurrenceState.PENDING)
    )
    if _pending_count(tasks, spawn.person) - freed + 1 > pending_limit:
        return _refused(TaskRefusal.PENDING_LIMIT)
    if replaced is not None:
        _cancel_pending(schedule, replaced)
    when = spawn.when
    due_at = (
        spawn.set_at
        if isinstance(when, DueNow)
        else when.at
        if isinstance(when, DueAt)
        else spawn.first_due_at
        if isinstance(when, DueOnRule)
        else _waits_ended(tasks, when)
    )
    try:
        task = ScheduledTask(
            id=spawn.id,
            person=spawn.person,
            author=spawn.author,
            when=when,
            places=spawn.places if replaced is None else replaced.places,
            instruction=spawn.instruction,
            parent=spawner if replaced is None else replaced.parent,
            set_in=spawn.set_in,
            set_at=spawn.set_at,
            outside_content=spawn.outside_content,
            chain_length=chain,
            occurrences=(ScheduledOccurrence(number=1, due_at=due_at),),
        )
    except ValidationError as exc:
        msg = f"the scheduled task {spawn.id} does not validate: {exc}"
        raise PlanningError(msg) from exc
    schedule.put(task)
    _release(schedule)
    return ScheduledTaskWrite(answer=TaskWriteAnswer.WRITTEN, task=schedule.tasks[task.id])


def decide_cancel(
    schedule: Schedule, task_id: str, *, person: str | None, spawned_by: str | None
) -> ScheduledTaskCancel:
    """Decide and apply one cancel (ADR-0350 §4:4, §9:5)."""
    task = schedule.tasks.get(task_id)
    if task is None:
        return ScheduledTaskCancel(reason=TaskRefusal.UNKNOWN_TASK)
    if person is not None and task.person != person:
        return ScheduledTaskCancel(reason=TaskRefusal.ANOTHER_PERSONS)
    if spawned_by is not None and task.parent != spawned_by:
        return ScheduledTaskCancel(reason=TaskRefusal.NOT_ITS_SPAWN)
    if not task.pending:
        return ScheduledTaskCancel(reason=TaskRefusal.NOTHING_PENDING)
    _cancel_pending(schedule, task)
    _release(schedule)
    return ScheduledTaskCancel(task=schedule.tasks[task_id])


def _rule_push_fault(
    task: ScheduledTask, occurrence: ScheduledOccurrence, rule: RulePush | None
) -> str | None:
    """Why a push's rule instants do not fit the pending occurrence, if they do not.

    A rule's occurrence never pushed takes them, and every other push takes none
    (ADR-0340 §9:3); the first instant they give is later than the pending one's.
    """
    first = isinstance(task.when, DueOnRule) and not occurrence.activations
    if first and rule is None:
        return (
            f"occurrence {occurrence.number} of rule {task.id} is first pushed with its "
            f"successor's instant, or none where the rule has ended (ADR-0340 §9:3)"
        )
    if not first and rule is not None:
        return (
            f"occurrence {occurrence.number} of {task.id} is pushed again or has no rule, so "
            f"its push writes no next occurrence (ADR-0340 §9:3)"
        )
    if rule is None:
        return None
    given = [*rule.skipped, rule.latest, rule.successor]
    later = next((one for one in given if one is not None), None)
    if later is not None and occurrence.due_at is not None and later <= occurrence.due_at:
        return (
            f"a rule's next occurrences fall due after occurrence {occurrence.number} of "
            f"{task.id} (ADR-0340 §4:6)"
        )
    return None


def _with_occurrences(
    task: ScheduledTask, occurrences: tuple[ScheduledOccurrence, ...]
) -> ScheduledTask:
    """``task`` holding ``occurrences``, revalidated."""
    try:
        return ScheduledTask.model_validate({**task.model_dump(), "occurrences": occurrences})
    except ValidationError as exc:
        msg = f"scheduled task {task.id} would no longer validate: {exc}"
        raise PlanningError(msg) from exc


def _new_occurrence(number: int, due_at: datetime, **state: Any) -> ScheduledOccurrence:
    """A new occurrence of a rule, numbered ``number``, at an instant its caller gave."""
    try:
        return ScheduledOccurrence(number=number, due_at=due_at, **state)
    except ValidationError as exc:
        msg = f"the rule's occurrence {number} would not validate: {exc}"
        raise PlanningError(msg) from exc


def _push_rule(
    schedule: Schedule,
    task: ScheduledTask,
    occurrence: ScheduledOccurrence,
    activation_id: str,
    rule: RulePush,
) -> None:
    """Push a rule's occurrence first pushed, and write what follows it (ADR-0340 §4:6-§4:8).

    Where it was missed more than once, the pending occurrence and each one between it
    and the latest end skipped, each with the instant it was due, and the latest is the
    one pushed. The successor, where the rule has not ended, is written pending last.
    Every new occurrence takes the next number, and none is ever renumbered (§4:10).
    """
    held = list(task.occurrences)
    number = len(held)
    if rule.latest is None:
        held[occurrence.number - 1] = _occurrence(
            occurrence, state=OccurrenceState.PUSHED, activations=(activation_id,)
        )
    else:
        held[occurrence.number - 1] = _occurrence(
            occurrence, state=OccurrenceState.SKIPPED, ended_at=schedule.now
        )
        for instant in rule.skipped:
            number += 1
            held.append(
                _new_occurrence(
                    number, instant, state=OccurrenceState.SKIPPED, ended_at=schedule.now
                )
            )
        number += 1
        held.append(
            _new_occurrence(
                number, rule.latest, state=OccurrenceState.PUSHED, activations=(activation_id,)
            )
        )
    if rule.successor is not None:
        held.append(_new_occurrence(number + 1, rule.successor))
    schedule.put(_with_occurrences(task, tuple(held)))


def decide_push(
    schedule: Schedule,
    task_id: str,
    number: int,
    activation_id: str,
    *,
    rule: RulePush | None = None,
) -> OccurrencePush:
    """Decide and apply one push (ADR-0350 §7:5, ADR-0352 §2:3).

    For a rule's occurrence first pushed, ``rule`` gives its successor and any it skips,
    written in the same step (ADR-0340 §4:6, §4:8, §9:3). Nothing in the task's lineage
    refuses it: a stop record on an activation above it leaves the push as it is.

    Raises:
        PlanningError: If the task holds no such occurrence, the occurrence is pending
            but not yet due, an occurrence was already pushed to ``activation_id``, or
            ``rule`` does not fit the push: given for a task with no rule or a push
            again, missing for a rule's first push, or no later than the pending one.
    """
    if task_of(schedule.tasks, activation_id) is not None:
        msg = f"an occurrence was already pushed to activation {activation_id} (ADR-0350 §7:5)"
        raise PlanningError(msg)
    task = schedule.tasks.get(task_id)
    if task is None:
        return OccurrencePush.NOT_PENDING
    if rule is not None and not isinstance(task.when, DueOnRule):
        msg = f"scheduled task {task_id} has no rule, so its push writes no next occurrence"
        raise PlanningError(msg)
    occurrence = task.occurrence(number)
    if occurrence is None:
        msg = f"scheduled task {task_id} holds no occurrence {number}"
        raise PlanningError(msg)
    if occurrence.state is not OccurrenceState.PENDING:
        return OccurrencePush.NOT_PENDING
    if occurrence.due_at is None:
        msg = f"occurrence {number} of scheduled task {task_id} waits on tasks not yet ended"
        raise PlanningError(msg)
    fault = _rule_push_fault(task, occurrence, rule)
    if fault is not None:
        raise PlanningError(fault)
    if rule is not None:
        _push_rule(schedule, task, occurrence, activation_id, rule)
        return OccurrencePush.PUSHED
    schedule.put(
        _rebuilt(
            task,
            _occurrence(
                occurrence,
                state=OccurrenceState.PUSHED,
                activations=(*occurrence.activations, activation_id),
            ),
        )
    )
    return OccurrencePush.PUSHED


def _pushed(
    tasks: dict[str, ScheduledTask], activation_id: str
) -> tuple[ScheduledTask, ScheduledOccurrence] | None:
    """The task and occurrence pushed to ``activation_id``, or ``None``."""
    for task in tasks.values():
        for one in task.occurrences:
            if one.pushed_to == activation_id:
                return task, one
    return None


def is_pushed(tasks: dict[str, ScheduledTask], activation_id: str) -> bool:
    """Whether an occurrence is pushed to ``activation_id`` (ADR-0350 §9:10)."""
    return _pushed(tasks, activation_id) is not None


def decide_settle(
    schedule: Schedule,
    activation_id: str,
    state: OccurrenceState,
    *,
    second_try: bool,
    stopped: bool,
) -> ScheduledTask:
    """Decide and apply an occurrence's outcome, or its push again (§7:6, §8:1-§8:7).

    Raises:
        PlanningError: If no occurrence is pushed to the activation, the state is not an
            outcome or ``pending``, ``second_try`` rides on an outcome, or a push again
            is asked for a second try or for an activation that carries a stop record.
    """
    found = _pushed(schedule.tasks, activation_id)
    if found is None:
        msg = f"no scheduled occurrence is pushed to activation {activation_id}"
        raise PlanningError(msg)
    task, occurrence = found
    if state is OccurrenceState.PENDING:
        if occurrence.second_try:
            msg = (
                f"activation {activation_id}'s occurrence was a second try, and is never "
                f"tried a third time (ADR-0350 §8:6)"
            )
            raise PlanningError(msg)
        if stopped:
            msg = (
                f"activation {activation_id} was stopped, so its occurrence is never pushed "
                f"again (ADR-0350 §8:1)"
            )
            raise PlanningError(msg)
        rebuilt = _rebuilt(
            task, _occurrence(occurrence, state=OccurrenceState.PENDING, second_try=second_try)
        )
    elif state in PUSHED_OUTCOMES:
        if second_try:
            msg = "only an occurrence pushed again is a second try (ADR-0350 §8:6)"
            raise PlanningError(msg)
        rebuilt = _rebuilt(task, _occurrence(occurrence, state=state, ended_at=schedule.now))
    else:
        msg = (
            f"an occurrence pushed ends done, couldn't finish, stopped or interrupted, not {state}"
        )
        raise PlanningError(msg)
    schedule.put(rebuilt)
    _release(schedule)
    return schedule.tasks[task.id]


def decide_removal(schedule: Schedule, task_id: str) -> bool:
    """Remove a task once nothing of it or below it is live, and none waits on it (§7:8).

    The parent's running is the caller's to hold, so it is not read here.
    """
    tasks = schedule.tasks
    task = tasks.get(task_id)
    if task is None or _live(task) or any(_live(one) for one in below(tasks, task)):
        return False
    if any(
        isinstance(one.when, DueAfterTasks) and task_id in one.when.tasks
        for one in tasks.values()
        if one.id != task_id
    ):
        return False
    del tasks[task_id]
    if task_id in schedule.changed:
        schedule.changed.remove(task_id)
    schedule.removed.append(task_id)
    return True


def decide_cascade_retirement(schedule: Schedule, cascades: Collection[str]) -> tuple[str, ...]:
    """Apply, once, the reach of cascade records a stop wrote before ADR-0352 (§2:6).

    The SQLite plan store's upgrade that retires the cascade record decides it here.
    Every task whose lineage carries one of ``cascades`` — the task's parent, or the
    parent of any task above it — has each pending occurrence ended *cancelled*, as
    ADR-0350 §7:5's push step refused it before ADR-0352 (a rule's successor among them,
    so the rule ends); and every occurrence of such a task marked pushed, its outcome
    unwritten, is named for a stop record, so ADR-0350 §8:1 ends it *stopped* at start
    and never pushes it again. A task waiting on one that ends here falls due as any
    waiting task does (§5:4).

    Args:
        schedule: The store's schedule, read in the upgrade's transaction.
        cascades: The activation ids the store's cascade records name.

    Returns:
        The activations of the pushed occurrences below a cascade record, in the order
        their tasks were written, each once: the stop records the upgrade writes.
    """
    named = frozenset(cascades)
    stops: list[str] = []
    for task in list(schedule.tasks.values()):
        if not any(one.parent in named for one in _above(schedule.tasks, task)):
            continue
        for one in task.occurrences:
            pushed = one.pushed_to
            if pushed is not None and pushed not in stops:
                stops.append(pushed)
        if any(one.state is OccurrenceState.PENDING for one in task.occurrences):
            _cancel_pending(schedule, task)
    _release(schedule)
    return tuple(stops)
