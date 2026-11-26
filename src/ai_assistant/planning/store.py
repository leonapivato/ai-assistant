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

**A store bound to a sight** (ADR-0383 §7) is a copy of this one sharing its records, its
stop records, its revision issuer and its clock by reference, with the sight set; every
write mutates the shared containers in place, so a write through either is read through
both. Withholding, it holds a record its sight sees by its home or, for an effect or an
approval request, as made by its sight's activation (§7:4), and every read and every
decision a write rests on reads the held records alone; a write's own checks, the stop,
an identifier or a key already taken and a revision, read every record (§7:11). Counting,
it answers as unbound, and each read logs the homes of the records it gave back.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActivationEffectClaim,
    ApprovalOutcomePush,
    ApprovalRequestWrite,
    ApprovalWriteAnswer,
    ObservationRecord,
    PlanExport,
    RecordHome,
    ScheduledTaskWrite,
    SightMode,
    TaskWriteAnswer,
    TicketClaim,
)
from ai_assistant.planning._home_columns import count_given, person_home
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
from ai_assistant.planning.approvals import (
    Book,
    by_token,
    checked_at,
    checked_card,
    checked_new_request,
    checked_plain_effect,
    checked_request_effect,
    checked_request_id,
    checked_spawn_key,
    checked_tap,
    checked_ticket_effect,
    checked_token,
    decide_answer,
    decide_card,
    decide_expiry,
    decide_outcome_push,
    decide_request_write,
    decide_ticket,
    decide_void,
    requested_request_ids,
    requested_request_states,
    spend_ticket,
    ticket_refused_write,
    write_request,
)
from ai_assistant.planning.approvals import (
    by_person as requests_by_person,
)
from ai_assistant.planning.approvals import checked_person as checked_request_person
from ai_assistant.planning.approvals import due as approvals_due
from ai_assistant.planning.approvals import (
    pushed as pushed_outcomes,
)
from ai_assistant.planning.observations import (
    checked_expected_revision,
    checked_observation,
    checked_since,
    decide_observation_home,
    decide_observation_write,
    requested_episodes,
    stamped,
)
from ai_assistant.planning.scheduled_tasks import (
    Schedule,
    below,
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
    task_of,
)
from ai_assistant.planning.stops import revalidated_activation_id

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import (
        ActivationEffect,
        ApprovalCard,
        ApprovalDue,
        ApprovalRequest,
        ApprovalRequestState,
        ApprovalRequestStep,
        ApprovalTap,
        OccurrencePush,
        OccurrenceState,
        QuestionPart,
        RulePush,
        ScheduledDue,
        ScheduledTask,
        ScheduledTaskCancel,
        Sight,
        TaskSpawn,
        ToolOutcome,
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class _Revisions:
    """The observation revision issuer every binding of one store shares (ADR-0329 §16:9)."""

    last: int = 0


def _effects_given(
    effects: Iterable[ActivationEffect],
) -> Iterator[tuple[RecordHome | None, str | None]]:
    """Each effect record as §11:1's count reads it: its home, and its activation (§7:4)."""
    return ((one.home, one.activation_id) for one in effects)


def _tasks_given(tasks: Iterable[ScheduledTask]) -> Iterator[tuple[RecordHome | None, str | None]]:
    """Each task as §11:1's count reads it: its person's domain, made by no activation."""
    return ((person_home(one.person), None) for one in tasks)


def _requests_given(
    requests: Iterable[ApprovalRequest],
) -> Iterator[tuple[RecordHome | None, str | None]]:
    """Each request as §11:1's count reads it: its person's domain, and who asked (§7:4)."""
    return ((person_home(one.person), one.activation_id) for one in requests)


class InMemoryPlanStore:
    """A non-persistent ``PlanStore`` backed by a set and a dict, for dev and tests.

    Structurally implements :class:`~ai_assistant.core.protocols.PlanStore`. Each effect
    and observation record it holds keeps its home, kind and identifier, as the record
    carries it (ADR-0386 §5), and a home no write may carry is refused before any step by
    the shared checks every writing member runs first (ADR-0386 §6).
    """

    def __init__(self, *, now: Clock = _utcnow, sight_mode: SightMode = SightMode.COUNT) -> None:
        """Create an empty store.

        Args:
            now: Clock for export timestamps; injectable for deterministic tests.
                Guarded by :func:`~ai_assistant.core.clock.checked_clock`, so a
                non-conforming reading is a ``PlanningError`` (ADR-0026).
            sight_mode: Whether a store bound to a sight withholds or only counts
                (ADR-0383 §7:10): fixed here, and read from no setting and no running act.
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
        # ADR-0361 §8:2: the Approvals channel's requests by id, in the order written.
        self._requests: dict[str, ApprovalRequest] = {}
        # The last revision issued. Never reset, `clear` included: an issuer reset by
        # it would reissue a stamp a writer may still hold (ADR-0329 §16:9).
        self._issuer = _Revisions()
        self._clock = checked_clock(now, owner="InMemoryPlanStore")
        self._sight_mode = sight_mode
        self._sight: Sight | None = None

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

    # --- a sight (ADR-0383 §7, §8, §11) ----------------------------------------

    def bound(self, sight: Sight) -> InMemoryPlanStore:
        """This store, bound to ``sight`` (ADR-0383 §7:1); the Protocol states the rest.

        A shallow copy sharing every container and the issuer by reference, with the
        sight set: the meet of the one it was already bound to, where it was (§6:6).

        Raises:
            ValueError: If this store is already bound to a sight of another reader or
                activation.
        """
        view = copy.copy(self)
        view._sight = sight if self._sight is None else self._sight.meet(sight)
        return view

    def _withholding_sight(self) -> Sight | None:
        """The sight this store withholds by, or ``None`` where it holds every record."""
        if self._sight is None or self._sight_mode is SightMode.COUNT:
            return None
        return self._sight

    def _held_effects(self) -> dict[str, ActivationEffect]:
        """The effect records this store, as bound, holds, in claim order (§7:2, §7:4)."""
        sight = self._withholding_sight()
        if sight is None:
            return self._activation_effects
        return {
            key: one
            for key, one in self._activation_effects.items()
            if sight.sees(one.home, made_by=one.activation_id)
        }

    def _held_observations(self) -> dict[str, ObservationRecord]:
        """The observation records this store, as bound, holds (§7:2)."""
        sight = self._withholding_sight()
        if sight is None:
            return self._observations
        return {key: one for key, one in self._observations.items() if sight.sees(one.home)}

    def _held_tasks(self, *, held: bool = True) -> dict[str, ScheduledTask]:
        """The tasks this store, as bound, holds, or with ``held`` false those it does not.

        A task is seen by its person's domain alone: no task is recorded as made by an
        activation (§3, §7:4).
        """
        sight = self._withholding_sight()
        if sight is None:
            return self._tasks if held else {}
        return {
            key: one
            for key, one in self._tasks.items()
            if sight.sees(person_home(one.person)) is held
        }

    def _held_requests(self, *, held: bool = True) -> dict[str, ApprovalRequest]:
        """The requests this store, as bound, holds, or with ``held`` false those it does not.

        A request is seen by its person's domain, or as asked by the sight's activation
        (§7:4).
        """
        sight = self._withholding_sight()
        if sight is None:
            return self._requests if held else {}
        return {
            key: one
            for key, one in self._requests.items()
            if sight.sees(person_home(one.person), made_by=one.activation_id) is held
        }

    def _counted(self, member: str, given: Iterable[tuple[RecordHome | None, str | None]]) -> None:
        """Write §11:1's count of one read, where this store is bound and only counts."""
        if self._sight is not None and self._sight_mode is SightMode.COUNT:
            count_given(self._sight, member=member, given=given)

    # --- stop records and activation effect records ------------------------------

    async def record_stop(self, activation_id: str, /) -> None:
        """Write a stop record naming ``activation_id``, idempotently (ADR-0297 §1).

        Raises:
            PlanningError: If ``activation_id`` is not an identifier.
        """
        self._stopped.add(revalidated_activation_id(activation_id))

    def _decided(
        self,
        record: ActivationEffect,
        named: tuple[str, ...] | None,
        deliberate_repeat: bool,
        *,
        spends: bool = False,
    ) -> ActivationEffectClaim:
        """Decide a claim's stop, held id, spend and backstop, with no write.

        The stop, the id and the part a call spends are a write's own checks, read over
        every record (ADR-0383 §7:11); the backstop matches the records this store, as
        bound, holds (§7:2).
        """
        return decide_activation_claim(
            record,
            match=named,
            deliberate_repeat=deliberate_repeat,
            stopped=record.activation_id in self._stopped,
            held_ids=self._activation_effects,
            matched=(
                ()
                if named is None
                else [held for held in self._held_effects().values() if held.activation_id in named]
            ),
            spent=spends
            and record.part is not None
            and any(held.part == record.part for held in self._activation_effects.values()),
        )

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
        record = checked_plain_effect(revalidated_claim(effect))
        named = matched_activations(match)
        answer = self._decided(record, named, deliberate_repeat, spends=True)
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
        held = self._held_effects().get(named)
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
        found = tuple(
            held.model_copy(deep=True)
            for held in self._held_effects().values()
            if held.activation_id in named
        )
        self._counted("activation_effects", _effects_given(found))
        return found

    async def part_effects(self, parts: Sequence[QuestionPart], /) -> tuple[ActivationEffect, ...]:
        """Return the records carrying any of ``parts``, in claim order (ADR-0321 §4:9).

        Raises:
            PlanningError: If ``parts`` holds anything but a ``QuestionPart``.
        """
        named = set(requested_parts(parts))
        found = tuple(
            held.model_copy(deep=True)
            for held in self._held_effects().values()
            if held.part is not None and held.part in named
        )
        self._counted("part_effects", _effects_given(found))
        return found

    async def write_observation(
        self, record: ObservationRecord, /, *, expected_revision: int
    ) -> ObservationRecord:
        """Write an episode's observation record whole, conditionally (ADR-0329 §16:9).

        Decided and written with no ``await`` between, which is this store's
        indivisible step.

        Raises:
            PlanningError: If the record is not valid, the expectation is not a
                revision, the held record does not match it, or, bound, a record this
                store does not hold is held for the episode.
        """
        written = checked_observation(record)
        expected = checked_expected_revision(expected_revision)
        held = self._observations.get(written.episode)
        if held is not None and written.episode not in self._held_observations():
            # ADR-0383 §7:5, §7:11: a write that would change a record this binding does
            # not hold is refused, and whether a record is held is read over every record.
            msg = (
                f"the plan store holds a record for episode {written.episode!r} this write "
                f"may not change; nothing is written"
            )
            raise PlanningError(msg)
        decide_observation_write(
            written.episode, held=None if held is None else held.revision, expected=expected
        )
        decide_observation_home(held, written)
        stored = stamped(written, self._issuer.last + 1)
        self._issuer.last = stored.revision
        self._observations[stored.episode] = stored
        return stored.model_copy(deep=True)

    async def observations(self, episode_ids: Sequence[str], /) -> tuple[ObservationRecord, ...]:
        """Return the named episodes' observation records, in the order named.

        Raises:
            PlanningError: If ``episode_ids`` is not a sequence of strings, or names an
                id with no UTF-8 encoding.
        """
        held = self._held_observations()
        found = tuple(
            held[one].model_copy(deep=True)
            for one in requested_episodes(episode_ids)
            if one in held
        )
        self._counted("observations", ((one.home, None) for one in found))
        return found

    async def observer_calls_since(self, since: datetime, /) -> int:
        """Count the model calls the observation records hold at or after ``since``.

        A store-wide figure that counts writes, answered alike bound or not (ADR-0383
        §8:5).

        Raises:
            PlanningError: If ``since`` is not a timezone-aware instant.
        """
        start = checked_since(since)
        calls = sum(record.call_count(start) for record in self._observations.values())
        self._counted("observer_calls_since", ())
        return calls

    # --- the Task Scheduler's scheduled tasks (ADR-0350 §12:3) -------------

    def _schedule(self) -> Schedule:
        """The schedule one step decides over: a copy, so a raise leaves the held tasks.

        The tasks this store, as bound, holds. The clock is read once for the step.
        :meth:`_kept_schedule` writes back what the decision changed.
        """
        return Schedule(tasks=dict(self._held_tasks()), now=self._now())

    def _kept_schedule(self, schedule: Schedule) -> None:
        """Write back, in place, the tasks a decision changed and remove those it removed."""
        for task_id in schedule.removed:
            self._tasks.pop(task_id, None)
        for task_id in schedule.changed:
            self._tasks[task_id] = schedule.tasks[task_id]

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
        indivisible step. A refusal writes neither the task nor the effect record, and
        leaves a ticket the spawn ran under held (ADR-0362 §3:1-§3:2).

        Raises:
            ClaimStopped: If the store holds a stop record for the spawning activation.
            PlanningError: If the spawn, the effect or a limit is not valid, an id is
                already held, or the effect's capability is not its ticket's call's.
        """
        asked = checked_spawn(spawn)
        record = checked_spawn_effect(checked_spawn_key(revalidated_claim(effect)))
        named = matched_activations(match)
        chain = checked_limit(chain_limit, "chain limit")
        pending = checked_limit(pending_limit, "pending limit")
        book: Book | None = None
        if record.ticket is None:
            answer = self._decided(record, named, deliberate_repeat, spends=True)
            if answer is not ActivationEffectClaim.CLAIMED:
                return ScheduledTaskWrite(answer=TaskWriteAnswer(answer.value))
        else:
            book, refused = self._ticket_refusal(record, named, deliberate_repeat)
            if refused is not None:
                return ticket_refused_write(refused)
        if asked.id in self._tasks:
            # ADR-0383 §7:11: whether a task already has the id is read over every task.
            msg = f"the plan store already holds scheduled task {asked.id} (ADR-0350 §3:3)"
            raise PlanningError(msg)
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
            if book is not None:
                spend_ticket(book, record)
                self._kept_book(book)
            self._kept_schedule(schedule)
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
        self._kept_schedule(schedule)
        return answer.model_copy(deep=True)

    async def scheduled_tasks(self, task_ids: Sequence[str], /) -> tuple[ScheduledTask, ...]:
        """Return the named tasks the store holds, in the order named (§12:3).

        Raises:
            PlanningError: If ``task_ids`` is not a sequence of encodable strings.
        """
        named = requested_ids(task_ids, "scheduled tasks")
        held = self._held_tasks()
        found = tuple(held[one].model_copy(deep=True) for one in named if one in held)
        self._counted("scheduled_tasks", _tasks_given(found))
        return found

    async def person_scheduled_tasks(
        self, person: str, states: Sequence[OccurrenceState], /
    ) -> tuple[ScheduledTask, ...]:
        """Return a person's tasks with an occurrence in any of ``states`` (§4:6).

        Raises:
            PlanningError: If ``person`` or ``states`` is not valid.
        """
        whose = checked_person(person)
        wanted = requested_states(states)
        found = tuple(
            one.model_copy(deep=True) for one in by_person(self._held_tasks(), whose, wanted)
        )
        self._counted("person_scheduled_tasks", _tasks_given(found))
        return found

    async def spawned_tasks(self, activation_ids: Sequence[str], /) -> tuple[ScheduledTask, ...]:
        """Return the tasks whose parent is any of the named activations (§12:3).

        Raises:
            PlanningError: If ``activation_ids`` is not a sequence of encodable strings.
        """
        named = requested_ids(activation_ids, "spawned tasks")
        found = tuple(one.model_copy(deep=True) for one in spawned_by(self._held_tasks(), named))
        self._counted("spawned_tasks", _tasks_given(found))
        return found

    async def scheduled_lineage(self, activation_id: str, /) -> tuple[ScheduledTask, ...]:
        """Return the lineage of the task pushed to ``activation_id`` (§6:5).

        Raises:
            PlanningError: If ``activation_id`` is not an identifier.
        """
        named = checked_id(activation_id, "activation")
        found = tuple(one.model_copy(deep=True) for one in lineage(self._held_tasks(), named))
        self._counted("scheduled_lineage", _tasks_given(found))
        return found

    async def live_below(self, task_id: str, /) -> bool:
        """Whether anything below a task is pending, pushed or running (§7:8).

        Raises:
            PlanningError: If ``task_id`` is not an identifier.
        """
        named = checked_id(task_id, "scheduled task")
        held = self._held_tasks()
        answer = live_below(held, named)
        task = held.get(named)
        self._counted(
            "live_below", _tasks_given(() if task is None else (task, *below(held, task)))
        )
        return answer

    async def due_occurrences(self, at: datetime, /) -> ScheduledDue:
        """Return the occurrences due at or before ``at``, and the next due after (§7:3).

        Raises:
            PlanningError: If ``at`` is not a timezone-aware instant.
        """
        found = due(self._held_tasks(), checked_instant(at)).model_copy(deep=True)
        self._counted("due_occurrences", _tasks_given(one.task for one in found.due))
        return found

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
        if task_of(self._held_tasks(held=False), pushed) is not None:
            # ADR-0383 §7:11: an activation an occurrence was pushed to is a key, read
            # over every task, as the unbound decision reads it first.
            msg = f"an occurrence was already pushed to activation {pushed} (ADR-0350 §7:5)"
            raise PlanningError(msg)
        schedule = self._schedule()
        answer = decide_push(schedule, named, which, pushed, rule=instants)
        self._kept_schedule(schedule)
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
        self._kept_schedule(schedule)
        return task.model_copy(deep=True)

    async def stop_pushed_activation(self, activation_id: str, /) -> bool:
        """Write a stop record for an activation pushed and not yet admitted (§9:10).

        Raises:
            PlanningError: If ``activation_id`` is not an identifier.
        """
        named = revalidated_activation_id(activation_id)
        if not is_pushed(self._held_tasks(), named):
            return False
        self._stopped.add(named)
        return True

    async def stopped_activations(self, activation_ids: Sequence[str], /) -> tuple[str, ...]:
        """Return which of the named activations the store holds a stop record for.

        Bound and withholding, none: a stop record carries no home, and no bound store
        gives one back (ADR-0383 §3:3).

        Raises:
            PlanningError: If ``activation_ids`` is not a sequence of encodable strings.
        """
        named = requested_ids(activation_ids, "stop records")
        if self._withholding_sight() is not None:
            return ()
        found = tuple(one for one in named if one in self._stopped)
        self._counted("stopped_activations", ((None, None) for _ in found))
        return found

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
            self._held_effects().get(named), named, delivered=delivered, position=position
        )

    async def remove_scheduled_task(self, task_id: str, /) -> bool:
        """Remove a task once nothing of it or below it is live (§7:8).

        Raises:
            PlanningError: If ``task_id`` is not an identifier.
        """
        named = checked_id(task_id, "scheduled task")
        schedule = self._schedule()
        removed = decide_removal(schedule, named)
        self._kept_schedule(schedule)
        return removed

    # --- the Approvals channel's requests (ADR-0361 §8:2) ------------------

    def _book(self) -> Book:
        """The requests one step decides over: a copy of those this store, as bound, holds."""
        return Book(requests=dict(self._held_requests()))

    def _kept_book(self, book: Book) -> None:
        """Write back, in place, the requests a decision changed, new or rewritten."""
        for request_id in book.changed:
            self._requests[request_id] = book.requests[request_id]

    def _ticket_refusal(
        self, record: ActivationEffect, named: tuple[str, ...] | None, deliberate_repeat: bool
    ) -> tuple[Book, TicketClaim | None]:
        """Decide a call under a ticket up to its write, as ``claim_ticket_call`` does.

        In order: the stop and the held id, the ticket and its key, and the backstop, a
        call under a ticket counting as one under an approval (ADR-0361 §5:3-§5:5). It
        answers the book the step decides over, and the refusal, or ``None`` where the
        caller writes the record and spends the ticket in the same step. The ticket's key
        is read over every effect record (ADR-0383 §7:11).
        """
        self._decided(record, None, deliberate_repeat)
        book = self._book()
        carried = any(held.ticket == record.ticket for held in self._activation_effects.values())
        refused = decide_ticket(book, record, carried=carried)
        if refused is not None:
            return book, refused
        if self._decided(record, named, deliberate_repeat) is not ActivationEffectClaim.CLAIMED:
            return book, TicketClaim.ALREADY_DONE
        return book, None

    async def write_approval_request(
        self,
        request: ApprovalRequest,
        effect: ActivationEffect,
        /,
        *,
        match: tuple[str, ...] | None,
        deliberate_repeat: bool = False,
    ) -> ApprovalRequestWrite:
        """Write a request with ``request_approval``'s effect claim, in one step (§2:8-§2:9).

        Decided and written with no ``await`` between, which is this store's
        indivisible step.

        Raises:
            ClaimStopped: If the store holds a stop record for the asking activation.
            PlanningError: If the request or the effect is not valid, or an id is held.
        """
        asked = checked_new_request(request)
        record = checked_request_effect(revalidated_claim(effect), asked)
        named = matched_activations(match)
        self._decided(record, None, deliberate_repeat)
        if asked.id in self._requests:
            # ADR-0383 §7:11: whether a request already has the id is read over every one.
            msg = f"the plan store already holds approval request {asked.id}"
            raise PlanningError(msg)
        book = self._book()
        waiting = decide_request_write(book, asked)
        if waiting is not None:
            return waiting.model_copy(deep=True)
        if self._decided(record, named, deliberate_repeat) is not ActivationEffectClaim.CLAIMED:
            return ApprovalRequestWrite(answer=ApprovalWriteAnswer.ALREADY_DONE)
        written = write_request(book, asked)
        self._kept_book(book)
        self._activation_effects[record.id] = record
        return written.model_copy(deep=True)

    async def approval_requests(self, request_ids: Sequence[str], /) -> tuple[ApprovalRequest, ...]:
        """Return the named requests the store holds, in the order named.

        Raises:
            PlanningError: If ``request_ids`` is not a sequence of encodable strings.
        """
        named = requested_request_ids(request_ids)
        held = self._held_requests()
        found = tuple(held[one].model_copy(deep=True) for one in named if one in held)
        self._counted("approval_requests", _requests_given(found))
        return found

    async def person_approval_requests(
        self, person: str, states: Sequence[ApprovalRequestState], /
    ) -> tuple[ApprovalRequest, ...]:
        """Return a person's requests in any of ``states``, in the order written (§4:6).

        Raises:
            PlanningError: If ``person`` or ``states`` is not valid.
        """
        whose = checked_request_person(person)
        wanted = requested_request_states(states)
        found = tuple(
            one.model_copy(deep=True)
            for one in requests_by_person(self._held_requests(), whose, wanted)
        )
        self._counted("person_approval_requests", _requests_given(found))
        return found

    async def approval_request_by_token(self, token: str, /) -> ApprovalRequest | None:
        """Return the request one of whose cards carries ``token``, or ``None`` (§4:10).

        Raises:
            PlanningError: If ``token`` is blank or has no UTF-8 encoding.
        """
        found = by_token(self._held_requests(), checked_token(token))
        self._counted(
            "approval_request_by_token", _requests_given(() if found is None else (found,))
        )
        return None if found is None else found.model_copy(deep=True)

    async def record_approval_card(self, request_id: str, card: ApprovalCard, /) -> ApprovalRequest:
        """Record one of a request's cards and its token, in one step (§4:3, §4:10).

        Raises:
            PlanningError: If an argument is not valid, no such request is held, or the
                token is already carried.
        """
        named = checked_request_id(request_id)
        posted = checked_card(card)
        book = self._book()
        written = decide_card(book, named, posted)
        if posted.token is not None and by_token(self._held_requests(held=False), posted.token):
            # ADR-0383 §7:11: a card's token is minted once, read over every request.
            msg = f"a card token is minted once, and approval request {named}'s is not new"
            raise PlanningError(msg)
        self._kept_book(book)
        return written.model_copy(deep=True)

    async def answer_approval_request(
        self, request_id: str, state: ApprovalRequestState, tap: ApprovalTap, /
    ) -> ApprovalRequestStep:
        """Answer a pending request by a tap, the first to land winning (§4:9).

        Raises:
            PlanningError: If an argument is not valid, or no such request is held.
        """
        named = checked_request_id(request_id)
        answer, tapped = checked_tap(state, tap)
        book = self._book()
        step = decide_answer(book, named, answer, tapped)
        self._kept_book(book)
        return step.model_copy(deep=True)

    async def expire_approval_request(
        self, request_id: str, at: datetime, /
    ) -> ApprovalRequestStep:
        """Expire a request, or void its held ticket, at its expiry (§3:5, §5:7).

        Raises:
            PlanningError: If an argument is not valid, no such request is held, or
                ``at`` is before its expiry.
        """
        named = checked_request_id(request_id)
        instant = checked_at(at)
        book = self._book()
        step = decide_expiry(book, named, instant)
        self._kept_book(book)
        return step.model_copy(deep=True)

    async def void_approval_ticket(self, request_id: str, /) -> ApprovalRequestStep:
        """Make a request's held ticket void (§5:7).

        Raises:
            PlanningError: If ``request_id`` is not valid, or no such request is held.
        """
        named = checked_request_id(request_id)
        book = self._book()
        step = decide_void(book, named)
        self._kept_book(book)
        return step.model_copy(deep=True)

    async def due_approval_outcomes(self, at: datetime, /) -> ApprovalDue:
        """Return the outcomes to push, the requests expiring, and the next expiry (§3:4).

        Raises:
            PlanningError: If ``at`` is not a timezone-aware instant.
        """
        found = approvals_due(self._held_requests(), checked_at(at)).model_copy(deep=True)
        self._counted("due_approval_outcomes", _requests_given((*found.outcomes, *found.expiring)))
        return found

    async def pushed_approval_outcomes(self) -> tuple[ApprovalRequest, ...]:
        """Return every request whose outcome is marked pushed, in the order written (§3:7)."""
        found = tuple(one.model_copy(deep=True) for one in pushed_outcomes(self._held_requests()))
        self._counted("pushed_approval_outcomes", _requests_given(found))
        return found

    async def mark_approval_outcome_pushed(
        self, request_id: str, activation_id: str, /
    ) -> ApprovalOutcomePush:
        """Mark a request's outcome pushed, naming its activation, in one step (§3:4).

        Raises:
            PlanningError: If an id is not valid, no such request is held, or the
                activation was already pushed to.
        """
        named = checked_request_id(request_id)
        pushed_to = checked_request_id(activation_id, "activation")
        book = self._book()
        answer = decide_outcome_push(book, named, pushed_to)
        if answer is ApprovalOutcomePush.PUSHED and any(
            one.pushed_to == pushed_to for one in self._held_requests(held=False).values()
        ):
            # ADR-0383 §7:11: an activation an outcome was pushed to is a key, read over
            # every request.
            msg = f"an approval's outcome was already pushed to activation {pushed_to}"
            raise PlanningError(msg)
        self._kept_book(book)
        return answer

    async def claim_ticket_call(
        self,
        effect: ActivationEffect,
        /,
        *,
        match: tuple[str, ...] | None,
        deliberate_repeat: bool = False,
    ) -> TicketClaim:
        """Claim a call under a ticket, keyed by its request, spending it (§5:3-§5:5).

        Decided and written with no ``await`` between, which is this store's
        indivisible step.

        Raises:
            ClaimStopped: If the store holds a stop record for the activation.
            PlanningError: If the effect is not valid, its id is held, or its capability
                is not the ticket's call's.
        """
        record = checked_ticket_effect(revalidated_claim(effect))
        named = matched_activations(match)
        book, refused = self._ticket_refusal(record, named, deliberate_repeat)
        if refused is not None:
            return refused
        spend_ticket(book, record)
        self._kept_book(book)
        self._activation_effects[record.id] = record
        return TicketClaim.CLAIMED

    async def export(self) -> PlanExport:
        """Return a portable, internally consistent snapshot (ADR-0004 §6).

        It carries what this store holds: the stop records, the activation effect
        records and the observation records. The sections ADR-0309 §5 retired (goals,
        plans, executions, attempts, questions, evidence and effect rows) left the
        document with them. Bound and withholding, the records it holds, and no stop
        record (ADR-0383 §3:3).

        Raises:
            PlanningError: If the injected clock's reading is not conforming
                (ADR-0026 §4).
        """
        observed = self._held_observations()
        document = PlanExport(
            exported_at=self._now(),
            # ADR-0297 §1: every stop record. A record names no goal, so only `clear`
            # takes one out.
            stopped_activations=(
                () if self._withholding_sight() is not None else tuple(sorted(self._stopped))
            ),
            # ADR-0306 §6: every effect record, in claim order.
            activation_effects=tuple(
                held.model_copy(deep=True) for held in self._held_effects().values()
            ),
            # ADR-0329 §16:9: every observation record, by episode id.
            observations=tuple(observed[one].model_copy(deep=True) for one in sorted(observed)),
            # ADR-0350 §12:3: every scheduled task, in the order written.
            scheduled_tasks=tuple(one.model_copy(deep=True) for one in self._held_tasks().values()),
            # ADR-0361 §8:2: every approval request, in the order written.
            approval_requests=tuple(
                one.model_copy(deep=True) for one in self._held_requests().values()
            ),
        )
        self._counted(
            "export",
            (
                *((None, None) for _ in document.stopped_activations),
                *_effects_given(document.activation_effects),
                *((one.home, None) for one in document.observations),
                *_tasks_given(document.scheduled_tasks),
                *_requests_given(document.approval_requests),
            ),
        )
        return document

    async def clear(self) -> int:
        """Delete every record, the Task Scheduler's included, returning the number removed.

        This store holds no execution, so no step is ever live and nothing refuses
        the erase. The revision issuer is kept (ADR-0329 §16:9). Bound and withholding,
        it removes and counts the records it holds, and no stop record (ADR-0383 §3:3).
        """
        doomed = (
            (self._activation_effects, list(self._held_effects())),
            (self._observations, list(self._held_observations())),
            (self._tasks, list(self._held_tasks())),
            (self._requests, list(self._held_requests())),
        )
        removed = 0
        if self._withholding_sight() is None:
            removed += len(self._stopped)
            self._stopped.clear()
        for records, keys in doomed:
            for key in keys:
                del records[key]
            removed += len(keys)
        return removed
