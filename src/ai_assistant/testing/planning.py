"""Canonical test doubles for the planning contracts (ADR-0014).

The shared fake for :class:`~ai_assistant.core.protocols.PlanStore`, so a
subsystem that depends on planning (orchestration, tools, ...) can test against a
real, contract-correct implementation *without importing the planning subsystem's
internals*
(CLAUDE.md golden rule 1).

It holds the seven members the phases use, and none that ADR-0309 §5 retires: the
stop record (ADR-0297 §1), acting's effect records (ADR-0306 §6) and their read by
question part (ADR-0321 §4:9), ``export`` and ``clear``; and the observer's three,
over its observation records (ADR-0329 §16:9). It deliberately
re-implements their rules rather than importing ``ai_assistant.planning``: importing
it would defeat the purpose, since a consumer's tests would then pull in the very
subsystem the fake stands in for.
The shared conformance suite is what keeps the two implementations honest — both
must pass it, so a divergence is a test failure rather than a latent surprise.

``FakePlanStore``'s reads *and* writes go through a
:class:`~ai_assistant.testing.cancellation.SuspendableResource` so it is a real
subject for the cancellation clause ``core.protocols`` states (ADR-0060), rather
than an implementation the obligation cannot reach. The reads are in because
``SqlitePlanStore`` answers every one of them from under its connection lock, so
each is its own place the resource could be handed over early (#397).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import ClaimStopped, PlanningError
from ai_assistant.core.types import (
    ActivationEffect,
    ActivationEffectClaim,
    Identifier,
    ObservationRecord,
    PlanExport,
    QuestionPart,
    ScheduledTaskWrite,
    TaskWriteAnswer,
    ToolOutcome,
    UtcInstant,
    encodable_text,
)
from ai_assistant.testing._scheduled_tasks import (
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
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import (
        OccurrencePush,
        OccurrenceState,
        RulePush,
        ScheduledDue,
        ScheduledTask,
        ScheduledTaskCancel,
        TaskSpawn,
    )
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog


#: Mirror of :data:`ai_assistant.planning.stops._ACTIVATION_ID`; see the module docstring
#: on duplication.
_ACTIVATION_ID: Final[TypeAdapter[Identifier]] = TypeAdapter(Identifier)

#: Mirror of :data:`ai_assistant.planning.observations._INSTANT`.
_INSTANT: Final[TypeAdapter[datetime]] = TypeAdapter(UtcInstant)

#: Mirror of :data:`ai_assistant.planning.observations._REVISION_BOUND`.
_REVISION_BOUND: Final = 2**63


def _revalidated_activation_id(activation_id: object) -> Identifier:
    """Return ``activation_id`` as the identifier a claim would name, or refuse it.

    Re-implemented here rather than imported from ``ai_assistant.planning``, for the
    reason this module's docstring gives (ADR-0297 §1).

    Raises:
        PlanningError: If the value is not an identifier.
    """
    try:
        return _ACTIVATION_ID.validate_python(activation_id)
    except ValidationError as exc:
        msg = f"a stop record names an activation id, and {activation_id!r} is not one"
        raise PlanningError(msg) from exc


def _claimable_effect(effect: object) -> ActivationEffect:
    """Return the fake's own copy of a record about to be claimed, or refuse it.

    Re-implemented here rather than imported from ``ai_assistant.planning``, for the
    reason this module's docstring gives (ADR-0306 §5:4, §6:2).

    Raises:
        PlanningError: If the value is not a valid ``ActivationEffect``, or it carries
            an outcome, a reason or a position.
    """
    if not isinstance(effect, ActivationEffect):
        msg = f"a claim writes an ActivationEffect, and {type(effect).__name__} is not one"
        raise PlanningError(msg)
    try:
        record = ActivationEffect.model_validate(effect.model_dump())
    except ValidationError as exc:
        msg = f"the activation effect to claim does not validate: {exc}"
        raise PlanningError(msg) from exc
    if record.outcome is not None or record.reason is not None or record.position is not None:
        msg = f"activation effect {record.id} is claimed before it runs, with no outcome"
        raise PlanningError(msg)
    return record


def _named_activations(match: object) -> tuple[str, ...] | None:
    """Return ``match`` as a tuple of activation ids, or refuse it (ADR-0306 §6:2).

    Re-implemented here rather than imported from ``ai_assistant.planning``, for the
    reason this module's docstring gives. An id with no UTF-8 encoding is refused, as
    the SQLite store must refuse it (issue #3288).

    Raises:
        PlanningError: If ``match`` is neither ``None`` nor a tuple of strings, or names
            an id with no UTF-8 encoding.
    """
    if match is None:
        return None
    if not isinstance(match, tuple) or not all(isinstance(one, str) for one in match):
        msg = "match is None or a tuple of activation ids (ADR-0306 §6:2)"
        raise PlanningError(msg)
    for index, one in enumerate(match):
        try:
            encodable_text(one)
        except ValueError as exc:
            msg = f"match names activation ids, and the one at index {index} is not: {exc}"
            raise PlanningError(msg) from exc
    return match


def _read_activations(activation_ids: object) -> tuple[str, ...]:
    """Return the activation ids a read names, each once in the order given, or refuse them.

    Re-implemented here rather than imported from ``ai_assistant.planning``, for the
    reason this module's docstring gives (ADR-0306 §6:5). An id with no UTF-8 encoding
    is refused, as the SQLite store must refuse it (issue #3291), and so is anything but
    a sequence, which the check would exhaust or fail to iterate (issue #3295).

    Raises:
        PlanningError: If ``activation_ids`` is a bare string, or not a sequence of
            strings, or names an id with no UTF-8 encoding.
    """
    if (
        not isinstance(activation_ids, Sequence)
        or isinstance(activation_ids, (str, bytes))
        or not all(isinstance(one, str) for one in activation_ids)
    ):
        msg = "activation_effects reads a sequence of activation ids (ADR-0306 §6:5)"
        raise PlanningError(msg)
    for index, one in enumerate(activation_ids):
        try:
            encodable_text(one)
        except ValueError as exc:
            msg = (
                f"activation_effects reads activation ids, and the one at index {index} "
                f"is not: {exc}"
            )
            raise PlanningError(msg) from exc
    return tuple(dict.fromkeys(activation_ids))


def _refuses_as_done(held: ActivationEffect, effect: ActivationEffect, *, deliberate: bool) -> bool:
    """Whether ``held`` refuses ``effect`` as already done (ADR-0306 §5:9, §5:11).

    A deliberate repeat under an approval passes an unknown or unwritten outcome
    (ADR-0321 §6:2).
    """
    if not (held.is_call and effect.is_call):
        return False
    if (held.capability, held.values_digest) != (effect.capability, effect.values_digest):
        return False
    if held.outcome is ToolOutcome.FAILED:
        return False
    if held.outcome is ToolOutcome.SUCCEEDED:
        return not deliberate
    return not (deliberate and effect.part is not None)


def _named_parts(parts: object) -> tuple[QuestionPart, ...]:
    """Return ``parts`` as the detached question parts a read names, or refuse them.

    Raises:
        PlanningError: If ``parts`` is a string, or not a sequence of ``QuestionPart``
            values.
    """
    if (
        not isinstance(parts, Sequence)
        or isinstance(parts, (str, bytes))
        or not all(isinstance(one, QuestionPart) for one in parts)
    ):
        msg = "part_effects reads a sequence of QuestionPart values (ADR-0321 §4:9)"
        raise PlanningError(msg)
    try:
        return tuple(dict.fromkeys(QuestionPart.model_validate(one.model_dump()) for one in parts))
    except ValidationError as exc:
        msg = f"a question part to read does not validate: {exc}"
        raise PlanningError(msg) from exc


def _finished_effect(
    held: ActivationEffect | None,
    effect_id: object,
    outcome: object,
    *,
    reason: object,
    position: object,
) -> ActivationEffect:
    """Return the record a finish writes, or refuse it (ADR-0306 §6:4).

    Raises:
        PlanningError: If the record is not held or already finished, the outcome is
            not a ``ToolOutcome``, the reason is blank or has no UTF-8 encoding, or the
            reason or position does not belong to it.
    """
    if held is None:
        msg = f"the plan store holds no activation effect {effect_id!r} to finish"
        raise PlanningError(msg)
    if held.outcome is not None:
        msg = f"activation effect {held.id} is already finished"
        raise PlanningError(msg)
    if not isinstance(outcome, ToolOutcome):
        msg = f"an activation effect finishes with a ToolOutcome, not {outcome!r}"
        raise PlanningError(msg)
    if reason is not None and outcome is not ToolOutcome.FAILED:
        msg = f"only an effect not done carries a reason; {held.id} cannot"
        raise PlanningError(msg)
    if position is not None and (held.is_call or outcome is not ToolOutcome.SUCCEEDED):
        msg = f"only a message done carries a position; {held.id} cannot"
        raise PlanningError(msg)
    try:
        return ActivationEffect.model_validate(
            {**held.model_dump(), "outcome": outcome, "reason": reason, "position": position}
        )
    except ValidationError as exc:
        msg = f"the finished activation effect {held.id} does not validate: {exc}"
        raise PlanningError(msg) from exc


#: Mirror of :data:`ai_assistant.planning.activation_effects.CONFIRMED_ABSENT`.
_CONFIRMED_ABSENT: Final = "its place's medium has no record of it (ADR-0350 §8:11)"


def _confirmed_effect(
    held: ActivationEffect | None, effect_id: str, *, delivered: object, position: object
) -> ActivationEffect:
    """Return the record a place's confirmation settles, or refuse it (ADR-0350 §8:11).

    Re-implemented here rather than imported from ``ai_assistant.planning``, for the
    reason this module's docstring gives.

    Raises:
        PlanningError: If no record is held, it is a call, its outcome is done or not
            done, ``delivered`` is not a ``bool``, or the position does not match it.
    """
    if held is None:
        msg = f"the plan store holds no activation effect {effect_id!r} to confirm"
        raise PlanningError(msg)
    if held.is_call:
        msg = f"activation effect {held.id} is a call; only a message's delivery is confirmed"
        raise PlanningError(msg)
    if held.outcome in {ToolOutcome.SUCCEEDED, ToolOutcome.FAILED}:
        msg = f"activation effect {held.id} is already settled"
        raise PlanningError(msg)
    if not isinstance(delivered, bool):
        msg = f"a confirmation says whether the message was recorded, not {delivered!r}"
        raise PlanningError(msg)
    if delivered != (position is not None):
        msg = "a message confirmed recorded carries its position, and one confirmed absent none"
        raise PlanningError(msg)
    try:
        return ActivationEffect.model_validate(
            {
                **held.model_dump(),
                "outcome": ToolOutcome.SUCCEEDED if delivered else ToolOutcome.FAILED,
                "reason": None if delivered else _CONFIRMED_ABSENT,
                "position": position,
            }
        )
    except ValidationError as exc:
        msg = f"the confirmed activation effect {held.id} does not validate: {exc}"
        raise PlanningError(msg) from exc


def _written_observation(record: object, expected: object) -> tuple[ObservationRecord, int]:
    """Return the fake's own copy of a record to write and its expectation, or refuse them.

    Re-implemented here rather than imported from ``ai_assistant.planning``, for the
    reason this module's docstring gives (ADR-0329 §16:9).

    Raises:
        PlanningError: If the record is not a valid ``ObservationRecord``, or the
            expectation is not a non-negative integer.
    """
    if not isinstance(record, ObservationRecord):
        msg = f"write_observation writes an ObservationRecord, not {type(record).__name__}"
        raise PlanningError(msg)
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        msg = f"expected_revision is 0 or a revision the store issued, not {expected!r}"
        raise PlanningError(msg)
    try:
        return ObservationRecord.model_validate(record.model_dump()), expected
    except ValidationError as exc:
        msg = f"the observation record to write does not validate: {exc}"
        raise PlanningError(msg) from exc


def _named_episodes(episode_ids: object) -> tuple[str, ...]:
    """Return the episodes a read names, each once in the order named, or refuse them.

    Re-implemented here rather than imported from ``ai_assistant.planning``, for the
    reason this module's docstring gives (ADR-0329 §16:9). An id with no UTF-8 encoding
    is refused, as the SQLite store must refuse it (issue #3191).

    Raises:
        PlanningError: If ``episode_ids`` is a bare string, or not a sequence of
            strings, or names an id with no UTF-8 encoding.
    """
    if (
        not isinstance(episode_ids, Sequence)
        or isinstance(episode_ids, (str, bytes))
        or not all(isinstance(one, str) for one in episode_ids)
    ):
        msg = "observations reads a sequence of episode ids (ADR-0329 §16:9)"
        raise PlanningError(msg)
    for index, one in enumerate(episode_ids):
        try:
            encodable_text(one)
        except ValueError as exc:
            msg = f"observations reads episode ids, and the one at index {index} is not: {exc}"
            raise PlanningError(msg) from exc
    return tuple(dict.fromkeys(episode_ids))


def _utcnow() -> datetime:
    return datetime.now(UTC)


class FakePlanStore:
    """A non-persistent ``PlanStore`` test double backed by a set and a dict.

    Structurally implements :class:`~ai_assistant.core.protocols.PlanStore`: the stop
    record, the activation effect records and the data-rights operations.
    """

    def __init__(self, *, now: Clock = _utcnow) -> None:
        """Create an empty store with an injectable clock.

        Args:
            now: Clock for export timestamps; injectable for deterministic tests.
                Guarded by :func:`~ai_assistant.core.clock.checked_clock`, exactly as
                ``InMemoryPlanStore`` is (ADR-0026 §7).
        """
        # ADR-0297 §1: one stop record per activation, carrying the id alone.
        self._stopped: set[str] = set()
        # ADR-0306 §6: acting's effect records by id, in claim order.
        self._activation_effects: dict[str, ActivationEffect] = {}
        # ADR-0329 §16:1: one observation record per episode, and the last revision
        # issued, which `clear` never resets.
        self._observations: dict[str, ObservationRecord] = {}
        self._issued = 0
        # ADR-0350 §12:3: the Task Scheduler's tasks by id, in the order written.
        self._tasks: dict[str, ScheduledTask] = {}
        self._clock = checked_clock(now, owner="FakePlanStore")
        self._resource = SuspendableResource()

    def suspend_next_operation(self) -> LoopSuspension:
        """Hold the next call that enters the modelled resource open inside it.

        The hook ``PlanStoreContract``'s cancellation case takes (ADR-0060 §3).
        Test-only, and not part of the ``PlanStore`` contract: the Protocol
        deliberately grows no affordance for this, so the suite asks the *subject*
        it was handed rather than the seam every consumer depends on.

        Named for an *operation* rather than a write because the reads enter the
        resource too (#397); it holds whichever call arrives next, so a suite arms
        it after its preconditions have run.

        Returns:
            The handle to wait on and release.
        """
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the modelled resource (ADR-0060's case reads it)."""
        return self._resource.log

    def _now(self) -> datetime:
        """The guarded clock's reading, as the error the real store raises.

        Raises:
            PlanningError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range
                (ADR-0026 §4).
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise PlanningError(str(exc)) from exc

    async def record_stop(self, activation_id: str, /) -> None:
        """Write a stop record naming ``activation_id``, idempotently (ADR-0297 §1).

        Under the modelled resource, like every other write.

        Raises:
            PlanningError: If ``activation_id`` is not an identifier.
        """
        named = _revalidated_activation_id(activation_id)
        async with self._resource.held():
            self._stopped.add(named)

    async def claim_activation_effect(
        self,
        effect: ActivationEffect,
        /,
        *,
        match: tuple[str, ...] | None,
        deliberate_repeat: bool = False,
    ) -> ActivationEffectClaim:
        """Claim one effect of an activation by writing its record (ADR-0306 §6:2).

        The stop, the id, the spend, the backstop and the write are decided under the
        modelled resource, with no ``await`` between.

        Raises:
            ClaimStopped: If the store holds a stop record for the activation.
            PlanningError: If the id is already held, the record carries an outcome,
                a reason or a position, or ``match`` names an id with no UTF-8
                encoding.
        """
        record = _claimable_effect(effect)
        named = _named_activations(match)
        async with self._resource.held():
            answer = self._decided_claim(record, named, deliberate_repeat=deliberate_repeat)
            if answer is ActivationEffectClaim.CLAIMED:
                self._activation_effects[record.id] = record
            return answer

    def _decided_claim(
        self, record: ActivationEffect, named: tuple[str, ...] | None, *, deliberate_repeat: bool
    ) -> ActivationEffectClaim:
        """Decide one claim, inside the caller's step: the claim's, or a spawn's (§3:3).

        Raises:
            ClaimStopped: If the store holds a stop record for the activation.
            PlanningError: If the id is already held.
        """
        if record.activation_id in self._stopped:
            msg = f"activation {record.activation_id} was stopped (ADR-0306 §5:2)"
            raise ClaimStopped(msg)
        if record.id in self._activation_effects:
            msg = f"the plan store already holds activation effect {record.id}"
            raise PlanningError(msg)
        if record.part is not None and any(
            held.part == record.part for held in self._activation_effects.values()
        ):
            return ActivationEffectClaim.ALREADY_USED
        if named is not None and any(
            _refuses_as_done(held, record, deliberate=deliberate_repeat)
            for held in self._activation_effects.values()
            if held.activation_id in named
        ):
            return ActivationEffectClaim.ALREADY_DONE
        return ActivationEffectClaim.CLAIMED

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
        try:
            named = _ACTIVATION_ID.validate_python(effect_id)
        except ValidationError as exc:
            msg = f"an activation effect is named by an identifier, not {effect_id!r}"
            raise PlanningError(msg) from exc
        async with self._resource.held():
            held = self._activation_effects.get(named)
            self._activation_effects[named] = _finished_effect(
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
        named = set(_read_activations(activation_ids))
        async with self._resource.held():
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
        named = set(_named_parts(parts))
        async with self._resource.held():
            return tuple(
                held.model_copy(deep=True)
                for held in self._activation_effects.values()
                if held.part is not None and held.part in named
            )

    async def write_observation(
        self, record: ObservationRecord, /, *, expected_revision: int
    ) -> ObservationRecord:
        """Write an episode's observation record whole, conditionally (ADR-0329 §16:9).

        The held revision and the write are decided under the modelled resource, with
        no ``await`` between.

        Raises:
            PlanningError: If the record is not valid, the expectation is not a
                revision, or the held record does not match it.
        """
        written, expected = _written_observation(record, expected_revision)
        async with self._resource.held():
            held = self._observations.get(written.episode)
            if (0 if held is None else held.revision) != expected:
                found = "no record" if held is None else f"revision {held.revision}"
                msg = (
                    f"the plan store holds {found} for episode {written.episode!r}, and the "
                    f"write expected {expected}; nothing is written"
                )
                raise PlanningError(msg)
            if self._issued + 1 >= _REVISION_BOUND:
                msg = "the plan store has issued every observation revision it can"
                raise PlanningError(msg)
            self._issued += 1
            stored = written.model_copy(update={"revision": self._issued})
            self._observations[stored.episode] = stored
            return stored.model_copy(deep=True)

    async def observations(self, episode_ids: Sequence[str], /) -> tuple[ObservationRecord, ...]:
        """Return the named episodes' observation records, in the order named.

        Raises:
            PlanningError: If ``episode_ids`` is not a sequence of strings, or names an
                id with no UTF-8 encoding.
        """
        named = _named_episodes(episode_ids)
        async with self._resource.held():
            return tuple(
                self._observations[one].model_copy(deep=True)
                for one in named
                if one in self._observations
            )

    async def observer_calls_since(self, since: datetime, /) -> int:
        """Count the model calls the observation records hold at or after ``since``.

        Raises:
            PlanningError: If ``since`` is not a timezone-aware instant.
        """
        try:
            start = _INSTANT.validate_python(since, strict=True)
        except ValidationError as exc:
            msg = f"observer_calls_since counts from a timezone-aware instant, not {since!r}"
            raise PlanningError(msg) from exc
        async with self._resource.held():
            return sum(record.call_count(start) for record in self._observations.values())

    # --- the Task Scheduler's scheduled tasks (ADR-0350 §12:3) -------------

    def _schedule(self) -> Schedule:
        """A copy of the schedule one step decides over, reading the clock once for it."""
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

        The claim, the replace, the wait, the limits and both writes are decided under
        the modelled resource, with no ``await`` between.

        Raises:
            ClaimStopped: If the store holds a stop record for the spawning activation.
            PlanningError: If the spawn, the effect or a limit is not valid, or an id is
                already held.
        """
        asked = checked_spawn(spawn)
        record = checked_spawn_effect(_claimable_effect(effect))
        named = _named_activations(match)
        chain = checked_limit(chain_limit, "chain limit")
        pending = checked_limit(pending_limit, "pending limit")
        async with self._resource.held():
            answer = self._decided_claim(record, named, deliberate_repeat=deliberate_repeat)
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
        async with self._resource.held():
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
        async with self._resource.held():
            return tuple(
                self._tasks[one].model_copy(deep=True) for one in named if one in self._tasks
            )

    async def person_scheduled_tasks(
        self, person: str, states: Sequence[OccurrenceState], /
    ) -> tuple[ScheduledTask, ...]:
        """Return a person's tasks with an occurrence in any of ``states`` (§4:6).

        Raises:
            PlanningError: If ``person`` or ``states`` is not valid.
        """
        whose = checked_person(person)
        wanted = requested_states(states)
        async with self._resource.held():
            return tuple(one.model_copy(deep=True) for one in by_person(self._tasks, whose, wanted))

    async def spawned_tasks(self, activation_ids: Sequence[str], /) -> tuple[ScheduledTask, ...]:
        """Return the tasks whose parent is any of the named activations (§12:3).

        Raises:
            PlanningError: If ``activation_ids`` is not a sequence of encodable strings.
        """
        named = requested_ids(activation_ids, "spawned tasks")
        async with self._resource.held():
            return tuple(one.model_copy(deep=True) for one in spawned_by(self._tasks, named))

    async def scheduled_lineage(self, activation_id: str, /) -> tuple[ScheduledTask, ...]:
        """Return the lineage of the task pushed to ``activation_id`` (§6:5).

        Raises:
            PlanningError: If ``activation_id`` is not an identifier.
        """
        named = checked_id(activation_id, "activation")
        async with self._resource.held():
            return tuple(one.model_copy(deep=True) for one in lineage(self._tasks, named))

    async def live_below(self, task_id: str, /) -> bool:
        """Whether anything below a task is pending, pushed or running (§7:8).

        Raises:
            PlanningError: If ``task_id`` is not an identifier.
        """
        named = checked_id(task_id, "scheduled task")
        async with self._resource.held():
            return live_below(self._tasks, named)

    async def due_occurrences(self, at: datetime, /) -> ScheduledDue:
        """Return the occurrences due at or before ``at``, and the next due after (§7:3).

        Raises:
            PlanningError: If ``at`` is not a timezone-aware instant.
        """
        instant = checked_instant(at)
        async with self._resource.held():
            return due(self._tasks, instant).model_copy(deep=True)

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
        async with self._resource.held():
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
        async with self._resource.held():
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
        named = _revalidated_activation_id(activation_id)
        async with self._resource.held():
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
        async with self._resource.held():
            return tuple(one for one in named if one in self._stopped)

    async def confirm_message_effect(
        self, effect_id: str, /, *, delivered: bool, position: int | None = None
    ) -> None:
        """Settle a message's effect record from its place's confirmation, once (§8:11).

        Raises:
            PlanningError: If the record is not held, is a call, is already settled, or
                the position does not match ``delivered``.
        """
        try:
            named = _ACTIVATION_ID.validate_python(effect_id)
        except ValidationError as exc:
            msg = f"an activation effect is named by an identifier, not {effect_id!r}"
            raise PlanningError(msg) from exc
        async with self._resource.held():
            self._activation_effects[named] = _confirmed_effect(
                self._activation_effects.get(named), named, delivered=delivered, position=position
            )

    async def remove_scheduled_task(self, task_id: str, /) -> bool:
        """Remove a task once nothing of it or below it is live (§7:8).

        Raises:
            PlanningError: If ``task_id`` is not an identifier.
        """
        named = checked_id(task_id, "scheduled task")
        async with self._resource.held():
            schedule = self._schedule()
            removed = decide_removal(schedule, named)
            self._tasks = schedule.tasks
            return removed

    async def export(self) -> PlanExport:
        """Return a portable, internally consistent snapshot — under the resource (#397).

        The sections ADR-0309 §5 retired (goals, plans, executions, attempts,
        questions, evidence and effect rows) left the document with them.
        """
        async with self._resource.held():
            return PlanExport(
                exported_at=self._now(),
                # ADR-0297 §1: every stop record, in a deterministic order.
                stopped_activations=tuple(sorted(self._stopped)),
                # ADR-0306 §6: every effect record, in claim order.
                activation_effects=tuple(
                    held.model_copy(deep=True) for held in self._activation_effects.values()
                ),
                # ADR-0329 §16:9: every observation record, by episode id.
                observations=tuple(
                    self._observations[one].model_copy(deep=True)
                    for one in sorted(self._observations)
                ),
                # ADR-0350 §12:3: every scheduled task, in the order written.
                scheduled_tasks=tuple(one.model_copy(deep=True) for one in self._tasks.values()),
            )

    async def clear(self) -> int:
        """Delete every record, the Task Scheduler's included, returning the number removed.

        This store holds no execution, so no step is ever live and nothing refuses
        the erase. The revision issuer is kept (ADR-0329 §16:9).
        """
        async with self._resource.held():
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


__all__ = ["FakePlanStore"]
