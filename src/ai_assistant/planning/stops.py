"""The stop record's two rules, stated once for every store in this package.

ADR-0297 §1 gives :class:`~ai_assistant.core.protocols.PlanStore` a stop record naming
one activation, and §2 has ``commit_transition`` refuse a ``→ RUNNING`` claim naming an
activation the store holds one for. Both are written here rather than in each store,
for the reason :mod:`ai_assistant.planning.goals` gives of its own refusals: two
statements of one rule are two places for it to drift, and the store's own job is the
indivisible step the decision is taken inside, not the decision.

The canonical fake in :mod:`ai_assistant.testing` re-implements this rather than
importing it, for the reason :mod:`ai_assistant.planning.effects` gives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.errors import ClaimStopped, PlanningError
from ai_assistant.core.types import Identifier, StepStatus

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import StepTransition

_ACTIVATION_ID: Final[TypeAdapter[Identifier]] = TypeAdapter(Identifier)


def revalidated_activation_id(activation_id: object) -> Identifier:
    """Return ``activation_id`` as the identifier a claim would name, or refuse it.

    ``record_stop`` refuses no activation id on the ground that the store does not
    know it (ADR-0297 §1:2). A value that is not an identifier at all is not an
    activation id, and it is validated by the type ``StepTransition.activation_id``
    carries, so a record and the claims it refuses compare one normalised value.

    Args:
        activation_id: What the caller passed.

    Returns:
        The validated identifier.

    Raises:
        PlanningError: If the value is not an identifier.
    """
    try:
        return _ACTIVATION_ID.validate_python(activation_id)
    except ValidationError as exc:
        msg = f"a stop record names an activation id, and {activation_id!r} is not one"
        raise PlanningError(msg) from exc


def refuse_a_stopped_claim(
    transition: StepTransition, *, is_stopped: Callable[[str], bool]
) -> None:
    """Refuse a ``→ RUNNING`` claim naming a stopped activation (ADR-0297 §2).

    The store passes ``is_stopped`` reading its own stop records **inside the step
    that commits the claim**, so there is no separate read on which the decision is
    taken. A claim naming no activation, and every transition but a claim, is not
    this conjunct's to refuse.

    Args:
        transition: The move being applied.
        is_stopped: Whether the store holds a stop record for an activation id.

    Raises:
        ClaimStopped: If the claim names an activation the store holds a stop record
            for.
    """
    if transition.to_status is not StepStatus.RUNNING or transition.activation_id is None:
        return
    if is_stopped(transition.activation_id):
        msg = (
            f"activation {transition.activation_id} was stopped, so its claim of step "
            f"{transition.step_id} on execution {transition.execution_id} is refused "
            f"(ADR-0297 §2)"
        )
        raise ClaimStopped(msg)
