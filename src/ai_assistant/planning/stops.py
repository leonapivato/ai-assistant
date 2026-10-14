"""What a stop record names, stated once for every store in this package.

ADR-0297 §1 gives :class:`~ai_assistant.core.protocols.PlanStore` a stop record naming
one activation, and ``record_stop`` refuses a value that is not an activation id. That
check is written here rather than in each store because two statements of one rule are
two places for it to drift, and the store's own job is the indivisible step the record
is written inside, not the rule. The claim a stop record refuses is decided in
:mod:`ai_assistant.planning.activation_effects`.

The canonical fake in :mod:`ai_assistant.testing` re-implements this rather than
importing it. That is the point of a conformance suite: the shared cases are what stop
the two drifting, and a fake that imported this module would pull in the subsystem it
stands in for.
"""

from __future__ import annotations

from typing import Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import Identifier

_ACTIVATION_ID: Final[TypeAdapter[Identifier]] = TypeAdapter(Identifier)


def revalidated_activation_id(activation_id: object) -> Identifier:
    """Return ``activation_id`` as the identifier a claim would name, or refuse it.

    ``record_stop`` refuses no activation id on the ground that the store does not
    know it (ADR-0297 §1:2). A value that is not an identifier at all is not an
    activation id, and it is validated by the type an effect record's
    ``activation_id`` carries, so a record and the claims it refuses compare one
    normalised value.

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
