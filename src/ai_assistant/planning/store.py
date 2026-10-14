"""An in-memory :class:`~ai_assistant.core.protocols.PlanStore` (ADR-0014 §5).

The dependency-free implementation of the planning contract. It keeps the stop
records and acting's effect records in process-local containers, so a consumer can
be built against a real store without a data directory.

It implements the six members the phases use, and none that ADR-0309 §5 retires: the
stop record (ADR-0297 §1), the activation effect records (ADR-0306 §6), and the
ADR-0004 data-rights operations (``export``/``clear``). It is **not persistent**: the
contract is resumable, this implementation is not, and that gap is named in
ADR-0014 §5 rather than hidden.
:class:`~ai_assistant.planning.sqlite_store.SqlitePlanStore` is the durable one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import ActivationEffectClaim, PlanExport
from ai_assistant.planning.activation_effects import (
    checked_effect_id,
    decide_activation_claim,
    finished,
    matched_activations,
    requested_activations,
    revalidated_claim,
)
from ai_assistant.planning.stops import revalidated_activation_id

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import ActivationEffect, ToolOutcome


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
            PlanningError: If the id is already held, or the record carries an
                outcome, a reason or a position.
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
            PlanningError: If the record is not held or already finished, or the
                reason or position does not belong to the outcome.
        """
        named = checked_effect_id(effect_id)
        held = self._activation_effects.get(named)
        self._activation_effects[named] = finished(
            held, named, outcome, reason=reason, position=position
        )

    async def activation_effects(
        self, activation_ids: Sequence[str], /
    ) -> tuple[ActivationEffect, ...]:
        """Return the named activations' effect records, in claim order (ADR-0306 §6:5)."""
        named = set(requested_activations(activation_ids))
        return tuple(
            held.model_copy(deep=True)
            for held in self._activation_effects.values()
            if held.activation_id in named
        )

    async def export(self) -> PlanExport:
        """Return a portable, internally consistent snapshot (ADR-0004 §6).

        It carries what this store holds: the stop records and the activation effect
        records. The sections ADR-0309 §5 retired (goals, plans, executions,
        attempts, questions, evidence and effect rows) export empty, since nothing
        here writes them.

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
        )

    async def clear(self) -> int:
        """Delete every stop and effect record, returning the number removed.

        This store holds no execution, so no step is ever live and nothing refuses
        the erase.
        """
        removed = len(self._stopped) + len(self._activation_effects)
        self._stopped.clear()
        self._activation_effects.clear()
        return removed
