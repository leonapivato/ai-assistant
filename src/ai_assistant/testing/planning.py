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
    ToolOutcome,
    UtcInstant,
    encodable_text,
)
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from ai_assistant.core.clock import Clock
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
            not a ``ToolOutcome``, or the reason or position does not belong to it.
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
            self._activation_effects[record.id] = record
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
            PlanningError: If the record is not held or already finished, or the
                reason or position does not belong to the outcome.
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
            )

    async def clear(self) -> int:
        """Delete every stop, effect and observation record, returning the number removed.

        This store holds no execution, so no step is ever live and nothing refuses
        the erase. The revision issuer is kept (ADR-0329 §16:9).
        """
        async with self._resource.held():
            removed = len(self._stopped) + len(self._activation_effects) + len(self._observations)
            self._stopped.clear()
            self._activation_effects.clear()
            self._observations.clear()
        return removed


__all__ = ["FakePlanStore"]
