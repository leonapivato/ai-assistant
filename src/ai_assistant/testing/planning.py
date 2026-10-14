"""Canonical test doubles for the planning contracts (ADR-0014).

The shared fake for :class:`~ai_assistant.core.protocols.PlanStore`, so a
subsystem that depends on planning (orchestration, tools, ...) can test against a
real, contract-correct implementation *without importing the planning subsystem's
internals*
(CLAUDE.md golden rule 1).

It holds the six members the phases use, and none that ADR-0309 §5 retires: the
stop record (ADR-0297 §1), acting's effect records (ADR-0306 §6), ``export`` and
``clear``. It deliberately re-implements their rules rather than importing
``ai_assistant.planning``: importing it would defeat the purpose, since a
consumer's tests would then pull in the very subsystem the fake stands in for.
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

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import ClaimStopped, PlanningError
from ai_assistant.core.types import (
    ActivationEffect,
    ActivationEffectClaim,
    Identifier,
    PlanExport,
    ToolOutcome,
)
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog


#: Mirror of :data:`ai_assistant.planning.stops._ACTIVATION_ID`; see the module docstring
#: on duplication.
_ACTIVATION_ID: Final[TypeAdapter[Identifier]] = TypeAdapter(Identifier)


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
    """Return ``match`` as a tuple of activation ids, or refuse it (ADR-0306 §6:2)."""
    if match is None:
        return None
    if not isinstance(match, tuple) or not all(isinstance(one, str) for one in match):
        msg = "match is None or a tuple of activation ids (ADR-0306 §6:2)"
        raise PlanningError(msg)
    return match


def _refuses_as_done(held: ActivationEffect, effect: ActivationEffect, *, deliberate: bool) -> bool:
    """Whether ``held`` refuses ``effect`` as already done (ADR-0306 §5:9, §5:11)."""
    if not (held.is_call and effect.is_call):
        return False
    if (held.capability, held.values_digest) != (effect.capability, effect.values_digest):
        return False
    if held.outcome is ToolOutcome.FAILED:
        return False
    if held.outcome is ToolOutcome.SUCCEEDED:
        return not deliberate
    return True


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

        The stop, the id, the backstop and the write are decided under the modelled
        resource, with no ``await`` between.

        Raises:
            ClaimStopped: If the store holds a stop record for the activation.
            PlanningError: If the id is already held, or the record carries an
                outcome, a reason or a position.
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
            PlanningError: If ``activation_ids`` is a bare string.
        """
        if isinstance(activation_ids, str):
            msg = "activation_effects reads a sequence of activation ids, not one string"
            raise PlanningError(msg)
        named = set(activation_ids)
        async with self._resource.held():
            return tuple(
                held.model_copy(deep=True)
                for held in self._activation_effects.values()
                if held.activation_id in named
            )

    async def export(self) -> PlanExport:
        """Return a portable, internally consistent snapshot — under the resource (#397).

        The sections ADR-0309 §5 retired (goals, plans, executions, attempts,
        questions, evidence and effect rows) export empty, since nothing here writes
        them.
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
            )

    async def clear(self) -> int:
        """Delete every stop and effect record, returning the number removed.

        This store holds no execution, so no step is ever live and nothing refuses
        the erase.
        """
        async with self._resource.held():
            removed = len(self._stopped) + len(self._activation_effects)
            self._stopped.clear()
            self._activation_effects.clear()
        return removed


__all__ = ["FakePlanStore"]
