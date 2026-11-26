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

**Bound to a sight** (ADR-0383 §7), :class:`FakePlanStore` is a copy sharing its records,
stop records, revision issuer, clock and modelled resource by reference, with the sight
set; every write mutates the shared containers in place. Withholding, it holds a record
its sight sees by its home or, for an effect or an approval request, as made by its
sight's activation (§7:4), and every read and every decision a write rests on reads the
held records alone, as the durable store does; a write's own checks read every record
(§7:11), and no stop record is given back (§3:3). Counting, it answers as unbound and logs
the homes of the records each read gave back. A test stand-in that subclasses it is bound
as itself, so its overrides run on the binding too.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import ClaimStopped, PlanningError
from ai_assistant.core.types import (
    ActivationEffect,
    ActivationEffectClaim,
    ApprovalOutcomePush,
    ApprovalRequest,
    ApprovalRequestWrite,
    ApprovalWriteAnswer,
    Identifier,
    ObservationRecord,
    PlanExport,
    QuestionPart,
    RecordHome,
    ScheduledTaskWrite,
    SightMode,
    TaskWriteAnswer,
    TicketClaim,
    ToolOutcome,
    UtcInstant,
    encodable_text,
    home_may_be_written,
)
from ai_assistant.testing._approvals import (
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
from ai_assistant.testing._approvals import by_person as requests_by_person
from ai_assistant.testing._approvals import checked_person as checked_request_person
from ai_assistant.testing._approvals import due as approvals_due
from ai_assistant.testing._approvals import pushed as pushed_outcomes
from ai_assistant.testing._home_count import count_given
from ai_assistant.testing._scheduled_tasks import (
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
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import (
        ApprovalCard,
        ApprovalDue,
        ApprovalRequestState,
        ApprovalRequestStep,
        ApprovalTap,
        OccurrencePush,
        OccurrenceState,
        RulePush,
        ScheduledDue,
        ScheduledTask,
        ScheduledTaskCancel,
        Sight,
        TaskSpawn,
    )
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog

#: The store's code in ADR-0383 §11:1's count event, as the durable store writes it.
_STORE_CODE: Final = "plans"


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


def _refuse_unwritable_home(home: RecordHome, *, record: str) -> None:
    """Refuse a record whose home no write may carry (ADR-0383 §4:7, ADR-0386 §6).

    Re-implemented here rather than imported from ``ai_assistant.planning``, for the
    reason this module's docstring gives. Called before any other step, so nothing is
    written.

    Raises:
        PlanningError: If ``home`` is one no write may carry.
    """
    if not home_may_be_written(home):
        msg = f"{record} lands in a {home.kind} home no write may carry (ADR-0383 §2:3)"
        raise PlanningError(msg)


def _claimable_effect(effect: object) -> ActivationEffect:
    """Return the fake's own copy of a record about to be claimed, or refuse it.

    Re-implemented here rather than imported from ``ai_assistant.planning``, for the
    reason this module's docstring gives (ADR-0306 §5:4, §6:2). Every member that writes
    an effect record takes it through here first, so a home no write may carry is
    refused before any other step (ADR-0386 §6).

    Raises:
        PlanningError: If the value is not a valid ``ActivationEffect``, it carries an
            outcome, a reason or a position, or its home is one no write may carry.
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
    _refuse_unwritable_home(record.home, record=f"activation effect {record.id}")
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
    return not (deliberate and effect.under_approval)


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
        PlanningError: If the record is not a valid ``ObservationRecord``, its home is
            one no write may carry (ADR-0386 §6), or the expectation is not a
            non-negative integer.
    """
    if not isinstance(record, ObservationRecord):
        msg = f"write_observation writes an ObservationRecord, not {type(record).__name__}"
        raise PlanningError(msg)
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        msg = f"expected_revision is 0 or a revision the store issued, not {expected!r}"
        raise PlanningError(msg)
    try:
        checked = ObservationRecord.model_validate(record.model_dump())
    except ValidationError as exc:
        msg = f"the observation record to write does not validate: {exc}"
        raise PlanningError(msg) from exc
    _refuse_unwritable_home(checked.home, record=f"the observation record of {checked.episode!r}")
    return checked, expected


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


def _person_home(person: str) -> RecordHome | None:
    """The home a task's or a request's person names: that person's domain (ADR-0383 §3).

    Mirror of ``ai_assistant.planning._home_columns.person_home`` for a record the fake
    holds, which is always valid.
    """
    try:
        return RecordHome.person(person)
    except ValidationError:
        return None


def _effects_given(
    effects: Iterable[ActivationEffect],
) -> Iterator[tuple[RecordHome | None, str | None]]:
    """Each effect record as §11:1's count reads it: its home, and its activation (§7:4)."""
    return ((one.home, one.activation_id) for one in effects)


def _tasks_given(tasks: Iterable[ScheduledTask]) -> Iterator[tuple[RecordHome | None, str | None]]:
    """Each task as §11:1's count reads it: its person's domain, made by no activation."""
    return ((_person_home(one.person), None) for one in tasks)


def _requests_given(
    requests: Iterable[ApprovalRequest],
) -> Iterator[tuple[RecordHome | None, str | None]]:
    """Each request as §11:1's count reads it: its person's domain, and who asked (§7:4)."""
    return ((_person_home(one.person), one.activation_id) for one in requests)


@dataclass
class _Revisions:
    """The observation revision issuer every binding of one fake shares (ADR-0329 §16:9)."""

    last: int = 0


class FakePlanStore:
    """A non-persistent ``PlanStore`` test double backed by a set and a dict.

    Structurally implements :class:`~ai_assistant.core.protocols.PlanStore`: the stop
    record, the activation effect records and the data-rights operations. Each effect and
    observation record keeps its home, kind and identifier, as the record carries it, and
    a home no write may carry is refused before any step (ADR-0386 §5, §6).
    """

    def __init__(self, *, now: Clock = _utcnow, sight_mode: SightMode = SightMode.COUNT) -> None:
        """Create an empty store with an injectable clock.

        Args:
            now: Clock for export timestamps; injectable for deterministic tests.
                Guarded by :func:`~ai_assistant.core.clock.checked_clock`, exactly as
                ``InMemoryPlanStore`` is (ADR-0026 §7).
            sight_mode: Whether a fake bound to a sight withholds or only counts
                (ADR-0383 §7:10), fixed here as the durable store fixes it.
        """
        # ADR-0297 §1: one stop record per activation, carrying the id alone.
        self._stopped: set[str] = set()
        # ADR-0306 §6: acting's effect records by id, in claim order.
        self._activation_effects: dict[str, ActivationEffect] = {}
        # ADR-0329 §16:1: one observation record per episode, and the last revision
        # issued, which `clear` never resets.
        self._observations: dict[str, ObservationRecord] = {}
        self._issuer = _Revisions()
        # ADR-0350 §12:3: the Task Scheduler's tasks by id, in the order written.
        self._tasks: dict[str, ScheduledTask] = {}
        # ADR-0361 §8:2: the Approvals channel's requests by id, in the order written.
        self._requests: dict[str, ApprovalRequest] = {}
        self._clock = checked_clock(now, owner="FakePlanStore")
        self._resource = SuspendableResource()
        self._sight_mode = sight_mode
        self._sight: Sight | None = None

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

    # --- a sight (ADR-0383 §7, §8, §11) ----------------------------------------

    def bound(self, sight: Sight) -> FakePlanStore:
        """This fake, bound to ``sight`` (ADR-0383 §7:1); the Protocol states the rest.

        A shallow copy, of the class it is, sharing every container, the issuer, the
        clock and the modelled resource by reference, with the sight set: the meet of
        the one it was already bound to, where it was (§6:6).

        The mode it answers in is :meth:`~ai_assistant.core.types.Sight.answered_in`'s:
        withholding for the owner's sight whatever mode this store was built in, with no
        count event (ADR-0385 §3:5), and the mode it was built in for every other.

        Raises:
            ValueError: If this fake is already bound to a sight of another reader or
                activation.
        """
        view = copy.copy(self)
        view._sight = sight if self._sight is None else self._sight.meet(sight)
        view._sight_mode = view._sight.answered_in(self._sight_mode)
        return view

    def _withholding_sight(self) -> Sight | None:
        """The sight this fake withholds by, or ``None`` where it holds every record."""
        if self._sight is None or self._sight_mode is SightMode.COUNT:
            return None
        return self._sight

    def _held_effects(self) -> dict[str, ActivationEffect]:
        """The effect records this fake, as bound, holds, in claim order (§7:2, §7:4)."""
        sight = self._withholding_sight()
        if sight is None:
            return self._activation_effects
        return {
            key: one
            for key, one in self._activation_effects.items()
            if sight.sees(one.home, made_by=one.activation_id)
        }

    def _held_observations(self) -> dict[str, ObservationRecord]:
        """The observation records this fake, as bound, holds (§7:2)."""
        sight = self._withholding_sight()
        if sight is None:
            return self._observations
        return {key: one for key, one in self._observations.items() if sight.sees(one.home)}

    def _held_tasks(self, *, held: bool = True) -> dict[str, ScheduledTask]:
        """The tasks this fake, as bound, holds, or with ``held`` false those it does not."""
        sight = self._withholding_sight()
        if sight is None:
            return self._tasks if held else {}
        return {
            key: one
            for key, one in self._tasks.items()
            if sight.sees(_person_home(one.person)) is held
        }

    def _held_requests(self, *, held: bool = True) -> dict[str, ApprovalRequest]:
        """The requests this fake, as bound, holds, or with ``held`` false those it does not."""
        sight = self._withholding_sight()
        if sight is None:
            return self._requests if held else {}
        return {
            key: one
            for key, one in self._requests.items()
            if sight.sees(_person_home(one.person), made_by=one.activation_id) is held
        }

    def _counted(self, member: str, given: Iterable[tuple[RecordHome | None, str | None]]) -> None:
        """Write §11:1's count of one read, where this fake is bound and only counts."""
        if self._sight is not None and self._sight_mode is SightMode.COUNT:
            count_given(self._sight, store=_STORE_CODE, member=member, given=given)

    # --- stop records and activation effect records ------------------------------

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
        record = checked_plain_effect(_claimable_effect(effect))
        named = _named_activations(match)
        async with self._resource.held():
            answer = self._decided_claim(record, named, deliberate_repeat=deliberate_repeat)
            if answer is ActivationEffectClaim.CLAIMED:
                self._activation_effects[record.id] = record
            return answer

    def _decided_claim(
        self,
        record: ActivationEffect,
        named: tuple[str, ...] | None,
        *,
        deliberate_repeat: bool,
    ) -> ActivationEffectClaim:
        """Decide one claim, inside the caller's step: the claim's, or a spawn's (§3:3).

        The stop, the id and the part a call spends are a write's own checks, read over
        every record (ADR-0383 §7:11); the backstop matches the records this fake, as
        bound, holds (§7:2).

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
            for held in self._held_effects().values()
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
            held = self._held_effects().get(named)
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
        named = set(_named_parts(parts))
        async with self._resource.held():
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

        The held revision and the write are decided under the modelled resource, with
        no ``await`` between.

        Raises:
            PlanningError: If the record is not valid, the expectation is not a
                revision, the held record does not match it, or, bound, a record this
                fake does not hold is held for the episode.
        """
        written, expected = _written_observation(record, expected_revision)
        async with self._resource.held():
            held = self._observations.get(written.episode)
            if held is not None and written.episode not in self._held_observations():
                # ADR-0383 §7:5, §7:11: a write that would change a record this binding
                # does not hold is refused, read over every record.
                msg = (
                    f"the plan store holds a record for episode {written.episode!r} this "
                    f"write may not change; nothing is written"
                )
                raise PlanningError(msg)
            if (0 if held is None else held.revision) != expected:
                found = "no record" if held is None else f"revision {held.revision}"
                msg = (
                    f"the plan store holds {found} for episode {written.episode!r}, and the "
                    f"write expected {expected}; nothing is written"
                )
                raise PlanningError(msg)
            if held is not None and held.home != written.home:
                # ADR-0383 §4:6: a record written again keeps the home it had.
                msg = (
                    f"no write changes the home of {written.episode!r}'s record; nothing is written"
                )
                raise PlanningError(msg)
            if self._issuer.last + 1 >= _REVISION_BOUND:
                msg = "the plan store has issued every observation revision it can"
                raise PlanningError(msg)
            self._issuer.last += 1
            stored = written.model_copy(update={"revision": self._issuer.last})
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
            held = self._held_observations()
            found = tuple(held[one].model_copy(deep=True) for one in named if one in held)
        self._counted("observations", ((one.home, None) for one in found))
        return found

    async def observer_calls_since(self, since: datetime, /) -> int:
        """Count the model calls the observation records hold at or after ``since``.

        A store-wide figure that counts writes, answered alike bound or not (ADR-0383
        §8:5).

        Raises:
            PlanningError: If ``since`` is not a timezone-aware instant.
        """
        try:
            start = _INSTANT.validate_python(since, strict=True)
        except ValidationError as exc:
            msg = f"observer_calls_since counts from a timezone-aware instant, not {since!r}"
            raise PlanningError(msg) from exc
        async with self._resource.held():
            calls = sum(record.call_count(start) for record in self._observations.values())
        self._counted("observer_calls_since", ())
        return calls

    # --- the Task Scheduler's scheduled tasks (ADR-0350 §12:3) -------------

    def _schedule(self) -> Schedule:
        """A copy of the tasks this fake, as bound, holds, with the clock read once."""
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

        The claim, a ticket the spawn runs under, the replace, the wait, the limits,
        both writes and the ticket's spend are decided under the modelled resource, with
        no ``await`` between. A refusal leaves the ticket held (ADR-0362 §3:1-§3:2).

        Raises:
            ClaimStopped: If the store holds a stop record for the spawning activation.
            PlanningError: If the spawn, the effect or a limit is not valid, an id is
                already held, or the effect's capability is not its ticket's call's.
        """
        asked = checked_spawn(spawn)
        record = checked_spawn_effect(checked_spawn_key(_claimable_effect(effect)))
        named = _named_activations(match)
        chain = checked_limit(chain_limit, "chain limit")
        pending = checked_limit(pending_limit, "pending limit")
        async with self._resource.held():
            book: Book | None = None
            if record.ticket is None:
                answer = self._decided_claim(record, named, deliberate_repeat=deliberate_repeat)
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
        async with self._resource.held():
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
        async with self._resource.held():
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
        async with self._resource.held():
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
        async with self._resource.held():
            found = tuple(
                one.model_copy(deep=True) for one in spawned_by(self._held_tasks(), named)
            )
        self._counted("spawned_tasks", _tasks_given(found))
        return found

    async def scheduled_lineage(self, activation_id: str, /) -> tuple[ScheduledTask, ...]:
        """Return the lineage of the task pushed to ``activation_id`` (§6:5).

        Raises:
            PlanningError: If ``activation_id`` is not an identifier.
        """
        named = checked_id(activation_id, "activation")
        async with self._resource.held():
            found = tuple(one.model_copy(deep=True) for one in lineage(self._held_tasks(), named))
        self._counted("scheduled_lineage", _tasks_given(found))
        return found

    async def live_below(self, task_id: str, /) -> bool:
        """Whether anything below a task is pending, pushed or running (§7:8).

        Raises:
            PlanningError: If ``task_id`` is not an identifier.
        """
        named = checked_id(task_id, "scheduled task")
        async with self._resource.held():
            held = self._held_tasks()
            answer = live_below(held, named)
            task = held.get(named)
            given = () if task is None else (task, *below(held, task))
        self._counted("live_below", _tasks_given(given))
        return answer

    async def due_occurrences(self, at: datetime, /) -> ScheduledDue:
        """Return the occurrences due at or before ``at``, and the next due after (§7:3).

        Raises:
            PlanningError: If ``at`` is not a timezone-aware instant.
        """
        instant = checked_instant(at)
        async with self._resource.held():
            found = due(self._held_tasks(), instant).model_copy(deep=True)
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
        async with self._resource.held():
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
        async with self._resource.held():
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
        named = _revalidated_activation_id(activation_id)
        async with self._resource.held():
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
        async with self._resource.held():
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
        try:
            named = _ACTIVATION_ID.validate_python(effect_id)
        except ValidationError as exc:
            msg = f"an activation effect is named by an identifier, not {effect_id!r}"
            raise PlanningError(msg) from exc
        async with self._resource.held():
            self._activation_effects[named] = _confirmed_effect(
                self._held_effects().get(named), named, delivered=delivered, position=position
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
            self._kept_schedule(schedule)
            return removed

    # --- the Approvals channel's requests (ADR-0361 §8:2) ------------------

    def _book(self) -> Book:
        """A copy of the requests this fake, as bound, holds, so a raise leaves them."""
        return Book(requests=dict(self._held_requests()))

    def _kept_book(self, book: Book) -> None:
        """Write back, in place, the requests a decision changed, new or rewritten."""
        for request_id in book.changed:
            self._requests[request_id] = book.requests[request_id]

    def _ticket_refusal(
        self, record: ActivationEffect, named: tuple[str, ...] | None, deliberate_repeat: bool
    ) -> tuple[Book, TicketClaim | None]:
        """Decide a call under a ticket up to its write, as ``claim_ticket_call`` does.

        In order (ADR-0361 §5:3-§5:5): the stop and the held id, the ticket and its key,
        and the backstop, a call under a ticket counting as one under an approval. It
        answers the book the step decides over, and the refusal, or ``None`` where the
        caller writes the record and spends the ticket in the same step. The ticket's key
        is read over every effect record (ADR-0383 §7:11).
        """
        self._decided_claim(record, None, deliberate_repeat=deliberate_repeat)
        book = self._book()
        carried = any(held.ticket == record.ticket for held in self._activation_effects.values())
        refused = decide_ticket(book, record, carried=carried)
        if refused is not None:
            return book, refused
        answer = self._decided_claim(record, named, deliberate_repeat=deliberate_repeat)
        if answer is not ActivationEffectClaim.CLAIMED:
            return book, TicketClaim.ALREADY_DONE
        return book, None

    def _step[T](
        self,
        decide: Callable[[Book], T],
        unheld: Callable[[dict[str, ApprovalRequest], T], None] | None = None,
    ) -> T:
        """Run one decision over a copy of the held book, and keep what it wrote.

        ``unheld``, where given, is a write's own check over the requests this fake, as
        bound, does not hold (ADR-0383 §7:11), run before anything is kept.
        """
        book = self._book()
        answer = decide(book)
        if unheld is not None:
            unheld(self._held_requests(held=False), answer)
        self._kept_book(book)
        return answer

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

        Raises:
            ClaimStopped: If the store holds a stop record for the asking activation.
            PlanningError: If the request or the effect is not valid, or an id is held.
        """
        asked = checked_new_request(request)
        record = checked_request_effect(_claimable_effect(effect), asked)
        named = _named_activations(match)
        async with self._resource.held():
            self._decided_claim(record, None, deliberate_repeat=deliberate_repeat)
            if asked.id in self._requests:
                # ADR-0383 §7:11: whether a request already has the id is read over every one.
                msg = f"the plan store already holds approval request {asked.id}"
                raise PlanningError(msg)
            book = self._book()
            waiting = decide_request_write(book, asked)
            if waiting is not None:
                return waiting.model_copy(deep=True)
            answer = self._decided_claim(record, named, deliberate_repeat=deliberate_repeat)
            if answer is not ActivationEffectClaim.CLAIMED:
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
        async with self._resource.held():
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
        async with self._resource.held():
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
        named = checked_token(token)
        async with self._resource.held():
            found = by_token(self._held_requests(), named)
            given = None if found is None else found.model_copy(deep=True)
        self._counted(
            "approval_request_by_token", _requests_given(() if given is None else (given,))
        )
        return given

    async def record_approval_card(self, request_id: str, card: ApprovalCard, /) -> ApprovalRequest:
        """Record one of a request's cards and its token, in one step (§4:3, §4:10).

        Raises:
            PlanningError: If an argument is not valid, no such request is held, or the
                token is already carried.
        """
        named = checked_request_id(request_id)
        posted = checked_card(card)

        def untaken(unheld: dict[str, ApprovalRequest], _written: ApprovalRequest) -> None:
            # ADR-0383 §7:11: a card's token is minted once, read over every request.
            if posted.token is not None and by_token(unheld, posted.token) is not None:
                msg = f"a card token is minted once, and approval request {named}'s is not new"
                raise PlanningError(msg)

        async with self._resource.held():
            return self._step(lambda book: decide_card(book, named, posted), untaken).model_copy(
                deep=True
            )

    async def answer_approval_request(
        self, request_id: str, state: ApprovalRequestState, tap: ApprovalTap, /
    ) -> ApprovalRequestStep:
        """Answer a pending request by a tap, the first to land winning (§4:9).

        Raises:
            PlanningError: If an argument is not valid, or no such request is held.
        """
        named = checked_request_id(request_id)
        answer, tapped = checked_tap(state, tap)
        async with self._resource.held():
            step = self._step(lambda book: decide_answer(book, named, answer, tapped))
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
        async with self._resource.held():
            step = self._step(lambda book: decide_expiry(book, named, instant))
            return step.model_copy(deep=True)

    async def void_approval_ticket(self, request_id: str, /) -> ApprovalRequestStep:
        """Make a request's held ticket void (§5:7).

        Raises:
            PlanningError: If ``request_id`` is not valid, or no such request is held.
        """
        named = checked_request_id(request_id)
        async with self._resource.held():
            return self._step(lambda book: decide_void(book, named)).model_copy(deep=True)

    async def due_approval_outcomes(self, at: datetime, /) -> ApprovalDue:
        """Return the outcomes to push, the requests expiring, and the next expiry (§3:4).

        Raises:
            PlanningError: If ``at`` is not a timezone-aware instant.
        """
        instant = checked_at(at)
        async with self._resource.held():
            found = approvals_due(self._held_requests(), instant).model_copy(deep=True)
        self._counted("due_approval_outcomes", _requests_given((*found.outcomes, *found.expiring)))
        return found

    async def pushed_approval_outcomes(self) -> tuple[ApprovalRequest, ...]:
        """Return every request whose outcome is marked pushed, in the order written (§3:7)."""
        async with self._resource.held():
            found = tuple(
                one.model_copy(deep=True) for one in pushed_outcomes(self._held_requests())
            )
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

        def untaken(unheld: dict[str, ApprovalRequest], answer: ApprovalOutcomePush) -> None:
            # ADR-0383 §7:11: an activation an outcome was pushed to is a key, read over
            # every request.
            if answer is ApprovalOutcomePush.PUSHED and any(
                one.pushed_to == pushed_to for one in unheld.values()
            ):
                msg = f"an approval's outcome was already pushed to activation {pushed_to}"
                raise PlanningError(msg)

        async with self._resource.held():
            return self._step(lambda book: decide_outcome_push(book, named, pushed_to), untaken)

    async def claim_ticket_call(
        self,
        effect: ActivationEffect,
        /,
        *,
        match: tuple[str, ...] | None,
        deliberate_repeat: bool = False,
    ) -> TicketClaim:
        """Claim a call under a ticket, keyed by its request, spending it (§5:3-§5:5).

        Raises:
            ClaimStopped: If the store holds a stop record for the activation.
            PlanningError: If the effect is not valid, its id is held, or its capability
                is not the ticket's call's.
        """
        record = checked_ticket_effect(_claimable_effect(effect))
        named = _named_activations(match)
        async with self._resource.held():
            book, refused = self._ticket_refusal(record, named, deliberate_repeat)
            if refused is not None:
                return refused
            spend_ticket(book, record)
            self._kept_book(book)
            self._activation_effects[record.id] = record
            return TicketClaim.CLAIMED

    async def export(self) -> PlanExport:
        """Return a portable, internally consistent snapshot — under the resource (#397).

        The sections ADR-0309 §5 retired (goals, plans, executions, attempts,
        questions, evidence and effect rows) left the document with them. Bound and
        withholding, the records it holds, and no stop record (ADR-0383 §3:3).
        """
        async with self._resource.held():
            observed = self._held_observations()
            document = PlanExport(
                exported_at=self._now(),
                # ADR-0297 §1: every stop record, in a deterministic order.
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
                scheduled_tasks=tuple(
                    one.model_copy(deep=True) for one in self._held_tasks().values()
                ),
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
        async with self._resource.held():
            removed = 0
            if self._withholding_sight() is None:
                removed += len(self._stopped)
                self._stopped.clear()
            for key in list(self._held_effects()):
                del self._activation_effects[key]
                removed += 1
            for key in list(self._held_observations()):
                del self._observations[key]
                removed += 1
            for key in list(self._held_tasks()):
                del self._tasks[key]
                removed += 1
            for key in list(self._held_requests()):
                del self._requests[key]
                removed += 1
        return removed


__all__ = ["FakePlanStore"]
