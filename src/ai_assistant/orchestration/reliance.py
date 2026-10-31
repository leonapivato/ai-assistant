"""Noting reliance: which memories shaped what planning did (ADR-0329 §6:7-§6:8).

Planning notes the memories it relied on by a call to a capability of its own, naming
each by its ``M`` label and saying in words what the reliance shaped. The round records
the call, and nothing else records it: the observer reads it from the round when the
episode leaves the window, and decides there whether to record a track-record entry
(§14:1). So the call has no effect, is safe to repeat, never leaves the hub, has no
unknown outcome and returns nothing (§6:7).

**Two parts, one module**: the declaration (:data:`NOTE_RELIANCE`), with which of its
arguments name things by label (:data:`RELIANCE_LABEL_ARGUMENTS`), and its answer,
:func:`noted`. Its effect is none, so acting hands it to the phases' invoker rather than
to the own-records seam (ADR-0306 §3:3, §5:7), and the phases' invoker answers it done
with :func:`noted`, reaching nothing.

It is offered beside ``remember``, which records a candidate (ADR-0329 §6:7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    Idempotency,
    LabelKind,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
    ToolResult,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "MEMORIES_ARGUMENT",
    "NOTE_RELIANCE",
    "NOTE_RELIANCE_CAPABILITY",
    "RELIANCE_LABEL_ARGUMENTS",
    "SHAPED_ARGUMENT",
    "noted",
]

#: The capability, and its one declaration's id.
NOTE_RELIANCE_CAPABILITY: Final = "note_reliance"

#: The memories relied on, by their ``M`` labels.
MEMORIES_ARGUMENT: Final = "memories"

#: What the reliance shaped, in words.
SHAPED_ARGUMENT: Final = "shaped"

#: The longest account of what a reliance shaped.
_SHAPED_MAX_CHARS: Final = 500

NOTE_RELIANCE: Final = ToolDefinition(
    id=NOTE_RELIANCE_CAPABILITY,
    capability=NOTE_RELIANCE_CAPABILITY,
    description=(
        "Note the memories you relied on, by their M labels, and say what the "
        "reliance shaped: a suggestion, an answer or an action. Note only a memory "
        "that shaped one, never one only mentioned in passing. Nothing runs; the note "
        "is kept with this round."
    ),
    risk_level=RiskLevel.LOW,
    reversibility=Reversibility.REVERSIBLE,
    side_effecting=False,
    reads=(),
    writes=(),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NATURAL,
    effect=CapabilityEffect.NONE,
    leaves_hub=False,
    result=CapabilityResult.NONE,
    outcome_can_be_unknown=False,
    safe_to_repeat=True,
    parameters_schema={
        "type": "object",
        "properties": {
            MEMORIES_ARGUMENT: {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
                "description": "The memories you relied on, by their M labels.",
            },
            SHAPED_ARGUMENT: {
                "type": "string",
                "minLength": 1,
                "maxLength": _SHAPED_MAX_CHARS,
                "description": "What relying on them shaped, in a few words.",
            },
        },
        "required": [MEMORIES_ARGUMENT, SHAPED_ARGUMENT],
        "additionalProperties": False,
    },
)
"""The reliance capability's declaration (ADR-0329 §6:7).

- ``effect=NONE``, ``safe_to_repeat=True``, ``leaves_hub=False``,
  ``outcome_can_be_unknown=False`` and ``result=NONE``: §6:7, each as ruled. A result
  of none returns nothing, so it returns no outside text.
- ``side_effecting=False`` with ``reads=()``, ``writes=()`` and ``discloses=()``: it
  changes and reads nothing; the round records it.
- ``reversibility=REVERSIBLE``, ``idempotency=NATURAL``: nothing to undo, and noting
  twice is the same note.
- ``risk_level=LOW``, ``cost=FREE``: nothing leaves the device and nothing is spent.
"""

#: Which of its arguments name things by label (ADR-0307 §5:2), which planning's check
#: maps to ids or refuses whole (§5:3).
RELIANCE_LABEL_ARGUMENTS: Final[Mapping[str, Mapping[str, LabelKind]]] = {
    NOTE_RELIANCE_CAPABILITY: {MEMORIES_ARGUMENT: LabelKind.MEMORY},
}


def noted() -> ToolResult:
    """A reliance call's answer: done, with nothing written and nothing returned.

    Returns:
        ``succeeded``, with no output.
    """
    return ToolResult(outcome=ToolOutcome.SUCCEEDED)
