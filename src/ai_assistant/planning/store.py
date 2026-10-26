"""An in-memory :class:`~ai_assistant.core.protocols.PlanStore` (ADR-0014 §5).

The dependency-free implementation of the planning contract. It keeps the stop
records and acting's effect records in process-local containers, so a consumer can
be built against a real store without a data directory.

It implements the seven members the phases use, and none that ADR-0309 §5 retires: the
stop record (ADR-0297 §1), the activation effect records (ADR-0306 §6) and their read
by question part (ADR-0321 §4:9), and the ADR-0004 data-rights operations
(``export``/``clear``); and the observer's three, over its observation records
(ADR-0329 §16:9). It is **not persistent**: the contract is resumable, this
implementation is not, and that gap is named in ADR-0014 §5 rather than hidden.
:class:`~ai_assistant.planning.sqlite_store.SqlitePlanStore` is the durable one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActivationEffectClaim,
    ObservationRecord,
    PlanExport,
    ScheduledTaskWrite,
    TaskWriteAnswer,
)
from ai_assistant.planning.activation_effects import (
    checked_effect_id,
    confirmed,
    decide_activation_claim,
    finished,
    matched_activations,
    requested_activations,
    requested_parts,
    revalidated_claim,
)
from ai_assistant.planning.observations import (
    checked_expected_revision,
    checked_observation,
    checked_since,
    decide_observation_write,
    requested_episodes,
    stamped,
)
from ai_assistant.planning.scheduled_tasks import (
    Schedule,
    by_person,
    checked_id,
    checked_instant,
    checked_limit,
    checked_number,
    checked_optional_id,
    checked_person,
    checked_rule_push,
    checked_spawn,
    checked_spawn_effect,
    checked_state,
    decide_cancel,
    decide_push,
    decide_removal,
    decide_settle,
    decide_task_write,
    due,
    is_pushed,
    lineage,
    live_below,
    requested_ids,
    requested_states,
    spawned_by,
)
from ai_assistant.planning.stops import revalidated_activation_id

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import (
        ActivationEffect,
        OccurrencePush,
        OccurrenceState,
        QuestionPart,
        RulePush,
        ScheduledDue,
        ScheduledTask,
        ScheduledTaskCancel,
        TaskSpawn,
        ToolOutcome,
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


class InMemoryPlanStore:
    """A non-persistent ``PlanStore`` backed by a set and a dict, for dev and tests.

    Structurally implements :class:`~ai_assistant.core.protocols.PlanStore`.
    """

    def __init__(self, *, now: Clock = _utcnow) -> None:
        """Create an empty store.

        Args:
            now: Clock for export timestamps; injectable for deterministic tests.
                Guarded by :func:`~ai_assistant.core.clock.checked_clock`, so a
                non-conforming reading is a ``PlanningError`` (ADR-0026).
        """
        # ADR-0297 §1: one stop record per activation, carrying the id alone. A set,
        # because a record has nothing but its identity and `record_stop` is
        # idempotent; ordered on export, so two exports of one store are one document.
        self._stopped: set[str] = set()
        # ADR-0306 §6: acting's effect records by id. A dict keeps insertion order,
        # which is claim order, and nothing removes one but `clear`.
        self._activation_effects: dict[str, ActivationEffect] = {}
        # ADR-0329 §16:1: one observation record per episode, by its id.
        self._observations: dict[str, ObservationRecord] = {}
        # ADR-0350 §12:3: the Task Scheduler's tasks by id, in the order written.
        self._tasks: dict[str, ScheduledTask] = {}
        # The last revision issued. Never reset, `clear` included: an issuer reset by
        # it would reissue a stamp a writer may still hold (ADR-0329 §16:9).
        self._issued = 0
        self._clock = checked_clock(now, owner="InMemoryPlanStore")

    def _now(self) -> datetime:
        """The guarded clock's reading, as `planning`'s own error (ADR-0026 §4).

        Raises:
            PlanningError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise PlanningError(str(exc)) from exc

    async def record_stop(self, activation_id: str, /) -> None:
        """Write a stop record naming ``activation_id``, idempotently (ADR-0297 §1).

        Raises:
            PlanningError: If ``activation_id`` is not an identifier.
        """
        self._stopped.add(revalidated_activation_id(activation_id))

    async def claim_activation_effect(
        self,
        effect: ActivationEffect,
        /,
        *,
        match: tuple[str, ...] | None,
        deliberate_repeat: bool = False,
    ) -> ActivationEffectClaim:
        """Claim one effect of an activation by writing its record (ADR-0306 §6:2).

        Decided and written with no ``await`` between, which is this store's
        indivisible step.

        Raises:
            ClaimStopped: If the store holds a stop record for the activation.
            PlanningError: If the id is already held, the record carries an outcome,
                a reason or a position, or ``match`` names an id with no UTF-8
                encoding.
        """
        record = revalidated_claim(effect)
        named = matched_activations(match)
        answer = decide_activation_claim(
            record,
            match=named,
            deliberate_repeat=deliberate_repeat,
            stopped=record.activation_id in self._stopped,
            held_ids=self._activation_effects,
            matched=(
                ()
                if named is None
                else [
                    held
                    for held in self._activation_effects.values()
                    if held.activation_id in named
                ]
            ),
            spent=record.part is not None
            and any(held.part == record.part for held in self._activation_effects.values()),
        )
        if answer is ActivationEffectClaim.CLAIMED:
            self._activation_effects[record.id] = record
        return answer

    async def finish_activation_effect(
        self,
        effect_id: str,
        /,
        outcome: ToolOutcome,
        *,
        reason: str | None = None,
        position: int | None = None,
    ) -> None:
        """Write a claimed effect's outcome, once (ADR-0306 §6:4).

        Raises:
            PlanningError: If ``effect_id`` is not an identifier, the record is not
                held or already finished, the reason is blank or has no UTF-8
                encoding, or the reason or position does not belong to the outcome.
        """
        named = checked_effect_id(effect_id)
        held = self._activation_effects.get(named)
        self._activation_effects[named] = finished(
            held, named, outcome, reason=reason, position=position
        )

    async def activation_effects(
        self, activation_ids: Sequence[str], /
    ) -> tuple[ActivationEffect, ...]:
        """Return the named activations' effect records, in claim order (ADR-0306 §6:5).

        Raises:
            PlanningError: If ``activation_ids`` is a bare string, or not a sequence
                of strings, or names an id with no UTF-8 encoding.
        """
        named = set(requested_activations(activation_ids))
        return tuple(
            held.model_copy(deep=True)
            for held in self._activation_effects.values()
            if held.activation_id in named
        )

    async def part_effects(self, parts: Sequence[QuestionPart], /) -> tuple[ActivationEffect, ...]:
        """Return the records carrying any of ``parts``, in claim order (ADR-0321 §4:9).

        Raises:
            PlanningError: If ``parts`` holds anything but a ``QuestionPart``.
        """
        named = set(requested_parts(parts))
        return tuple(
            held.model_copy(deep=True)
            for held in self._activation_effects.values()
            if held.part is not None and held.part in named
        )

    async def write_observation(
        self, record: ObservationRecord, /, *, expected_revision: int
    ) -> ObservationRecord:
        """Write an episode's observation record whole, conditionally (ADR-0329 §16:9).

        Decided and written with no ``await`` between, which is this store's
        indivisible step.

        Raises:
            PlanningError: If the record is not valid, the expectation is not a
                revision, or the held record does not match it.
        """
        written = checked_observation(record)
        expected = checked_expected_revision(expected_revision)
        held = self._observations.get(written.episode)
        decide_observation_write(
            written.episode, held=None if held is None else held.revision, expected=expected
        )
        stored = stamped(written, self._issued + 1)
        self._issued = stored.revision
        self._observations[stored.episode] = stored
        return stored.model_copy(deep=True)

    async def observations(self, episode_ids: Sequence[str], /) -> tuple[ObservationRecord, ...]:
        """Return the named episodes' observation records, in the order named.

        Raises:
            PlanningError: If ``episode_ids`` is not a sequence of strings, or names an
                id with no UTF-8 encoding.
        """
        return tuple(
            self._observations[one].model_copy(deep=True)
            for one in requested_episodes(episode_ids)
            if one in self._observations
        )

    async def observer_calls_since(self, since: datetime, /) -> int:
        """Count the model calls the observation records hold at or after ``since``.

        Raises:
            PlanningError: If ``since`` is not a timezone-aware instant.
        """
        start = checked_since(since)
        return sum(record.call_count(start) for record in self._observations.values())

    # --- the Task Scheduler's scheduled tasks (ADR-0350 §12:3) -------------

    def _schedule(self) -> Schedule:
        """The schedule one step decides over: a copy, so a raise leaves the held tasks.

        The clock is read once for the step. The writer assigns the copy back when the
        decision returns.
        """
        return Schedule(tasks=dict(self._tasks), now=self._now())

    async def write_scheduled_task(  # noqa: PLR0913 — the Protocol's signature
        self,
        spawn: TaskSpawn,
        effect: ActivationEffect,
        /,
        *,
        match: tuple[str, ...] | None,
        deliberate_repeat: bool = False,
        replace_any: bool = False,
        chain_limit: int,
        pending_limit: int,
    ) -> ScheduledTaskWrite:
        """Write a scheduled task with its spawn's effect claim, in one step (§3:3).

        Decided and written with no ``await`` between, which is this store's
        indivisible step. A refusal writes neither the task nor the effect record.

        Raises:
            ClaimStopped: If the store holds a stop record for the spawning activation.
            PlanningError: If the spawn, the effect or a limit is not valid, or an id is
                already held.
        """
        asked = checked_spawn(spawn)
        record = checked_spawn_effect(revalidated_claim(effect))
        named = matched_activations(match)
        chain = checked_limit(chain_limit, "chain limit")
        pending = checked_limit(pending_limit, "pending limit")
        answer = decide_activation_claim(
            record,
            match=named,
            deliberate_repeat=deliberate_repeat,
            stopped=record.activation_id in self._stopped,
            held_ids=self._activation_effects,
            matched=(
                ()
                if named is None
                else [
                    held
                    for held in self._activation_effects.values()
                    if held.activation_id in named
                ]
            ),
            spent=record.part is not None
            and any(held.part == record.part for held in self._activation_effects.values()),
        )
        if answer is not ActivationEffectClaim.CLAIMED:
            return ScheduledTaskWrite(answer=TaskWriteAnswer(answer.value))
        schedule = self._schedule()
        written = decide_task_write(
            schedule,
            asked,
            record.activation_id,
            replace_any=replace_any,
            chain_limit=chain,
            pending_limit=pending,
        )
        if written.answer is TaskWriteAnswer.WRITTEN:
            self._tasks = schedule.tasks
            self._activation_effects[record.id] = record
        return written.model_copy(deep=True)

    async def cancel_scheduled_task(
        self, task_id: str, /, *, person: str | None = None, spawned_by: str | None = None
    ) -> ScheduledTaskCancel:
        """End every pending occurrence of a task as cancelled (§9:5).

        Raises:
            PlanningError: If an id is not an identifier.
        """
        named = checked_id(task_id, "scheduled task")
        whose = None if person is None else checked_person(person)
        by = checked_optional_id(spawned_by, "spawning activation")
        schedule = self._schedule()
        answer = decide_cancel(schedule, named, person=whose, spawned_by=by)
        self._tasks = schedule.tasks
        return answer.model_copy(deep=True)

    async def scheduled_tasks(self, task_ids: Sequence[str], /) -> tuple[ScheduledTask, ...]:
        """Return the named tasks the store holds, in the order named (§12:3).

        Raises:
            PlanningError: If ``task_ids`` is not a sequence of encodable strings.
        """
        named = requested_ids(task_ids, "scheduled tasks")
        return tuple(self._tasks[one].model_copy(deep=True) for one in named if one in self._tasks)

    async def person_scheduled_tasks(
        self, person: str, states: Sequence[OccurrenceState], /
    ) -> tuple[ScheduledTask, ...]:
        """Return a person's tasks with an occurrence in any of ``states`` (§4:6).

        Raises:
            PlanningError: If ``person`` or ``states`` is not valid.
        """
        whose = checked_person(person)
        wanted = requested_states(states)
        return tuple(one.model_copy(deep=True) for one in by_person(self._tasks, whose, wanted))

    async def spawned_tasks(self, activation_ids: Sequence[str], /) -> tuple[ScheduledTask, ...]:
        """Return the tasks whose parent is any of the named activations (§12:3).

        Raises:
            PlanningError: If ``activation_ids`` is not a sequence of encodable strings.
        """
        named = requested_ids(activation_ids, "spawned tasks")
        return tuple(one.model_copy(deep=True) for one in spawned_by(self._tasks, named))

    async def scheduled_lineage(self, activation_id: str, /) -> tuple[ScheduledTask, ...]:
        """Return the lineage of the task pushed to ``activation_id`` (§6:5).

        Raises:
            PlanningError: If ``activation_id`` is not an identifier.
        """
        named = checked_id(activation_id, "activation")
        return tuple(one.model_copy(deep=True) for one in lineage(self._tasks, named))

    async def live_below(self, task_id: str, /) -> bool:
        """Whether anything below a task is pending, pushed or running (§7:8).

        Raises:
            PlanningError: If ``task_id`` is not an identifier.
        """
        return live_below(self._tasks, checked_id(task_id, "scheduled task"))

    async def due_occurrences(self, at: datetime, /) -> ScheduledDue:
        """Return the occurrences due at or before ``at``, and the next due after (§7:3).

        Raises:
            PlanningError: If ``at`` is not a timezone-aware instant.
        """
        return due(self._tasks, checked_instant(at)).model_copy(deep=True)

    async def mark_occurrence_pushed(
        self, task_id: str, number: int, activation_id: str, /, *, rule: RulePush | None = None
    ) -> OccurrencePush:
        """Mark a pending occurrence pushed, in one step (§7:5, ADR-0352 §2:3).

        A rule's occurrence first pushed writes its successor, and any it skips, in
        the same step (ADR-0340 §4:6, §4:8, §9:3).

        Raises:
            PlanningError: If an argument is not valid, the task holds no such
                occurrence, the activation was already pushed to, or ``rule`` does not
                fit the push.
        """
        named = checked_id(task_id, "scheduled task")
        which = checked_number(number)
        pushed = checked_id(activation_id, "activation")
        instants = checked_rule_push(rule)
        schedule = self._schedule()
        answer = decide_push(schedule, named, which, pushed, rule=instants)
        self._tasks = schedule.tasks
        return answer

    async def settle_occurrence(
        self, activation_id: str, state: OccurrenceState, /, *, second_try: bool = False
    ) -> ScheduledTask:
        """Write the outcome of the occurrence pushed to an activation (§7:6, §8).

        Raises:
            PlanningError: If no occurrence is pushed to it, or the outcome is refused.
        """
        named = checked_id(activation_id, "activation")
        outcome = checked_state(state)
        schedule = self._schedule()
        task = decide_settle(
            schedule,
            named,
            outcome,
            second_try=second_try is True,
            stopped=named in self._stopped,
        )
        self._tasks = schedule.tasks
        return task.model_copy(deep=True)

    async def stop_pushed_activation(self, activation_id: str, /) -> bool:
        """Write a stop record for an activation pushed and not yet admitted (§9:10).

        Raises:
            PlanningError: If ``activation_id`` is not an identifier.
        """
        named = revalidated_activation_id(activation_id)
        if not is_pushed(self._tasks, named):
            return False
        self._stopped.add(named)
        return True

    async def stopped_activations(self, activation_ids: Sequence[str], /) -> tuple[str, ...]:
        """Return which of the named activations the store holds a stop record for.

        Raises:
            PlanningError: If ``activation_ids`` is not a sequence of encodable strings.
        """
        named = requested_ids(activation_ids, "stop records")
        return tuple(one for one in named if one in self._stopped)

    async def confirm_message_effect(
        self, effect_id: str, /, *, delivered: bool, position: int | None = None
    ) -> None:
        """Settle a message's effect record from its place's confirmation, once (§8:11).

        Raises:
            PlanningError: If the record is not held, is a call, is already settled, or
                the position does not match ``delivered``.
        """
        named = checked_effect_id(effect_id)
        self._activation_effects[named] = confirmed(
            self._activation_effects.get(named), named, delivered=delivered, position=position
        )

    async def remove_scheduled_task(self, task_id: str, /) -> bool:
        """Remove a task once nothing of it or below it is live (§7:8).

        Raises:
            PlanningError: If ``task_id`` is not an identifier.
        """
        named = checked_id(task_id, "scheduled task")
        schedule = self._schedule()
        removed = decide_removal(schedule, named)
        self._tasks = schedule.tasks
        return removed

    async def export(self) -> PlanExport:
        """Return a portable, internally consistent snapshot (ADR-0004 §6).

        It carries what this store holds: the stop records, the activation effect
        records and the observation records. The sections ADR-0309 §5 retired (goals,
        plans, executions, attempts, questions, evidence and effect rows) left the
        document with them.

        Raises:
            PlanningError: If the injected clock's reading is not conforming
                (ADR-0026 §4).
        """
        return PlanExport(
            exported_at=self._now(),
            # ADR-0297 §1: every stop record. A record names no goal, so only `clear`
            # takes one out.
            stopped_activations=tuple(sorted(self._stopped)),
            # ADR-0306 §6: every effect record, in claim order.
            activation_effects=tuple(
                held.model_copy(deep=True) for held in self._activation_effects.values()
            ),
            # ADR-0329 §16:9: every observation record, by episode id.
            observations=tuple(
                self._observations[one].model_copy(deep=True) for one in sorted(self._observations)
            ),
            # ADR-0350 §12:3: every scheduled task, in the order written.
            scheduled_tasks=tuple(one.model_copy(deep=True) for one in self._tasks.values()),
        )

    async def clear(self) -> int:
        """Delete every record, the Task Scheduler's included, returning the number removed.

        This store holds no execution, so no step is ever live and nothing refuses
        the erase. The revision issuer is kept (ADR-0329 §16:9).
        """
        removed = (
            len(self._stopped)
            + len(self._activation_effects)
            + len(self._observations)
            + len(self._tasks)
        )
        self._stopped.clear()
        self._activation_effects.clear()
        self._observations.clear()
        self._tasks.clear()
        return removed
