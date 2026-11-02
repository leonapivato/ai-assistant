"""The register of calls that always need approval, by rule (ADR-0364 §7:5).

A rule that asks for approval of every call to a tool is said twice: authorizing applies
it, ruling the call needs the person, and each such tool's effects line says it always
needs approval first. Both read it from this one register, so the two cannot disagree.
It imports no phase module, so authorizing and the module that builds the offered tools
may each import it without one phase module importing another (ADR-0309 §2:3).

Today it holds ``send_email``, every email by rule from whichever account (ADR-0364
§9:12, as ADR-0021 §5's floor already has it), and the person model's three calls
(ADR-0338 §8:5, ADR-0364 §13:1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.orchestration.message_tools import EMAIL_CAPABILITY
from ai_assistant.orchestration.person_calls import PERSON_MODEL_CAPABILITIES

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "ALWAYS_NEEDS_APPROVAL",
    "ApprovalRule",
    "approval_rule",
]


@dataclass(frozen=True, slots=True)
class ApprovalRule:
    """One rule that always asks for approval of a tool's every call.

    Attributes:
        check: The name authorizing records the check under in the round's checks.
        reason: Why the call needs approval, in the words its refusal says.
    """

    check: str
    reason: str


#: ADR-0364 §7:5: each tool whose every call needs approval by rule, by its capability.
ALWAYS_NEEDS_APPROVAL: Final[Mapping[str, ApprovalRule]] = {
    EMAIL_CAPABILITY: ApprovalRule(
        check="email", reason="every email needs approval first, from whichever account"
    ),
    **{
        capability: ApprovalRule(
            check="person_model",
            reason="a change to the profile or the pins of the person this work is for needs "
            "approval first",
        )
        for capability in sorted(PERSON_MODEL_CAPABILITIES)
    },
}


def approval_rule(capability: str) -> ApprovalRule | None:
    """The rule that always asks for approval of ``capability``'s calls, or ``None``."""
    return ALWAYS_NEEDS_APPROVAL.get(capability)
