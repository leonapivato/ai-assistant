"""ADR-0364's two field additions: ``CallResult.outcome`` and ``RequestedCall.looking_for``.

§6:4: the outcome planning is shown rides on the call's result, ``None`` where it is shown
none, and never ``needs_you``, which planning is shown as refused (§6:3). §10:6: a
request keeps planning's *looking for* beside its deliberate-repeat mark, left out of a
dump where unset, and no part of the call that runs or of its sameness.
"""

from __future__ import annotations

from typing import Any, Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    CallOutcomeKind,
    CallResult,
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    Idempotency,
    RequestedCall,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)

_LOOKING_FOR: Final = "When does the museum open on Sunday?"


def _search() -> ToolDefinition:
    return ToolDefinition(
        id="web_search",
        capability="search_web",
        description="Search the web for a query.",
        risk_level=RiskLevel.LOW,
        reversibility=Reversibility.REVERSIBLE,
        side_effecting=True,
        reads=(),
        writes=(),
        discloses=(),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NATURAL,
        effect=CapabilityEffect.OWN_RECORDS,
        leaves_hub=False,
        result=CapabilityResult.MAY_CARRY_OUTSIDE_TEXT,
        outcome_can_be_unknown=False,
        safe_to_repeat=True,
        parameters_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )


def _call(**overrides: Any) -> RequestedCall:
    fields: dict[str, Any] = {"tool": _search(), "values": {"query": "museum hours"}}
    fields.update(overrides)
    return RequestedCall(**fields)


@pytest.mark.parametrize(
    "outcome",
    [
        CallOutcomeKind.DONE,
        CallOutcomeKind.NOT_DONE,
        CallOutcomeKind.UNKNOWN,
        CallOutcomeKind.REFUSED,
        None,
    ],
)
def test_a_result_carries_the_outcome_planning_is_shown(outcome: CallOutcomeKind | None) -> None:
    """§6:4: one of the four, or none."""
    result = CallResult(call_id="toolu_1", text='{"outcome": "done"}', outcome=outcome)

    assert result.outcome is outcome
    assert CallResult.model_validate_json(result.model_dump_json()) == result


def test_a_result_written_before_the_outcome_reads_as_showing_none() -> None:
    """§6:4: defaulting to ``None``, so a recorded exchange reads unchanged."""
    assert CallResult.model_validate({"call_id": "toolu_1", "text": "done"}).outcome is None


def test_a_result_is_never_shown_as_needing_you() -> None:
    """§6:3-§6:4: a call needing approval is shown as refused."""
    with pytest.raises(ValidationError, match="refused"):
        CallResult(call_id="toolu_1", text="x", outcome=CallOutcomeKind.NEEDS_YOU)


def test_a_request_keeps_its_looking_for_and_reads_it_back() -> None:
    """§10:2, §10:6: recorded with the request, and read back whole."""
    call = _call(looking_for=_LOOKING_FOR)

    assert call.looking_for == _LOOKING_FOR
    assert call.model_dump(mode="json")["looking_for"] == _LOOKING_FOR
    assert RequestedCall.model_validate_json(call.model_dump_json()) == call


def test_a_request_without_one_dumps_as_before() -> None:
    """§10:6: left out of a dump where ``None``, so a stored request is stored as it was."""
    dumped = _call().model_dump(mode="json")

    assert "looking_for" not in dumped
    assert set(dumped) == {"tool", "values", "binding", "deliberate_repeat", "replaces"}


def test_looking_for_is_no_part_of_the_call_or_its_sameness() -> None:
    """§10:6: not in the values, not in the request, and no part of ``same_call``."""
    kept = _call(looking_for=_LOOKING_FOR)

    assert "looking_for" not in kept.values
    assert kept.request == _call().request
    assert kept.same_call(_call())
    assert kept.same_call(_call(looking_for="Something else entirely?"))


def test_a_blank_looking_for_is_refused() -> None:
    with pytest.raises(ValidationError):
        _call(looking_for="   ")
