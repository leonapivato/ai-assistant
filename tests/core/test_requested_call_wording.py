"""ADR-0338 §8:6 with ADR-0361 §2:11: a request's call records the wording its line shows.

The exact line of a ``pin`` or an ``unpin`` shows the memory's wording as the store held
it when the round was recorded, and a card shows that exact line, so the wording is held
with the request: ``RequestedCall.wording``. It is carried only by a call whose exact line
shows one, it is never blank, it is no part of the call that runs or of its sameness, and
a dump leaves it out where it is unset, so every request stored before it serialises as
it did. A request carrying one is an export of a new shape, so the label moves to 28.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    WORDED_CAPABILITIES,
    ApprovalRequest,
    CapabilityEffect,
    CostBasis,
    Idempotency,
    PlanExport,
    RequestedCall,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.testing import with_phase_declaration

_AT: Final = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
_WORDING: Final = "Robin is vegetarian."


def _tool(capability: str, argument: str = "memory") -> ToolDefinition:
    fields: dict[str, object] = {
        "id": capability,
        "capability": capability,
        "description": f"The {capability} call.",
        "risk_level": RiskLevel.LOW,
        "reversibility": Reversibility.RECOVERABLE,
        # As ADR-0338 §8:4 declares the three: the assistant's own records, safe to repeat.
        "side_effecting": True,
        "effect": CapabilityEffect.OWN_RECORDS,
        "leaves_hub": False,
        "outcome_can_be_unknown": False,
        "safe_to_repeat": True,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NATURAL,
        "parameters_schema": {
            "type": "object",
            "properties": {argument: {"type": "string"}},
            "required": [argument],
        },
    }
    return ToolDefinition(**with_phase_declaration(fields))  # type: ignore[arg-type]  # heterogeneous test kwargs


def _call(capability: str = "pin", **overrides: Any) -> RequestedCall:
    fields: dict[str, Any] = {"tool": _tool(capability), "values": {"memory": "m:diet"}}
    fields.update(overrides)
    return RequestedCall(**fields)


def _request(call: RequestedCall) -> ApprovalRequest:
    return ApprovalRequest(
        id="q1",
        person="person:owner",
        activation_id="act-ask",
        round="r1",
        call=call,
        why="You asked me to keep it in mind.",
        written_at=_AT,
        expires_at=_AT + timedelta(hours=24),
    )


def test_the_worded_capabilities_are_a_pin_and_an_unpin() -> None:
    """§8:6 names the two whose exact line shows a memory by its wording."""
    assert frozenset({"pin", "unpin"}) == WORDED_CAPABILITIES


@pytest.mark.parametrize("capability", ["pin", "unpin"])
def test_a_pins_or_an_unpins_call_carries_its_wording_and_round_trips(capability: str) -> None:
    """The wording is held with the request, and a stored request reads it back whole."""
    request = _request(_call(capability, wording=_WORDING))

    assert request.call.wording == _WORDING
    assert request.model_dump(mode="json")["call"]["wording"] == _WORDING
    assert ApprovalRequest.model_validate_json(request.model_dump_json()) == request


def test_an_unworded_call_is_left_out_of_a_dump_and_reads_as_it_did() -> None:
    """A request of every earlier form is stored and exported byte for byte as before.

    The dump of a call with no wording is the dump the previous release wrote, with no
    ``wording`` key, and a stored request with none validates unchanged.
    """
    before = _call()
    dumped = before.model_dump(mode="json")

    assert before.wording is None
    assert "wording" not in dumped
    assert set(dumped) == {"tool", "values", "binding", "deliberate_repeat", "replaces"}
    stored = _request(before).model_dump_json()
    assert ApprovalRequest.model_validate_json(stored).model_dump_json() == stored


@pytest.mark.parametrize("capability", ["book_stay", "remember", "set_profile", "Pin"])
def test_a_call_whose_line_shows_no_wording_carries_none(capability: str) -> None:
    """Only a pin's or an unpin's line shows a memory's wording in place of its id.

    Any other call's line shows every value as it is sent, so a wording there would show
    the person something the call does not send. The refusal names neither the
    capability nor the wording.
    """
    with pytest.raises(ValidationError, match="ADR-0338") as refused:
        _call(capability, wording="PRIVATE_WORDING")

    assert "PRIVATE_WORDING" not in str(refused.value)


@pytest.mark.parametrize(
    "wording",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="blank"),
        pytest.param("PRIVATE\ud800", id="no-encoding"),
    ],
)
def test_a_wording_is_never_blank_and_never_rendered_in_a_refusal(wording: str) -> None:
    """ADR-0145 §8: the wording is the person's memory text, kept out of the error."""
    with pytest.raises(ValidationError) as refused:
        _call(wording=wording)

    assert "PRIVATE" not in str(refused.value)


def test_the_wording_is_shown_never_sent_and_no_part_of_the_calls_sameness() -> None:
    """ADR-0361 §2:8, §5:2: the call a ticket runs, and the duplicate check, ignore it."""
    worded = _call(wording=_WORDING)
    reworded = _call(wording="Robin eats no meat.")

    assert worded.request == _call().request
    assert worded.same_call(_call())
    assert worded.same_call(reworded)
    assert not worded.same_call(_call(values={"memory": "m:sister"}, wording=_WORDING))


def test_an_export_holding_a_worded_request_is_at_twenty_eight_and_round_trips() -> None:
    """ADR-0039 §10: a reader of 27 would refuse the wording as extra, so the label moves."""
    export = PlanExport(exported_at=_AT, approval_requests=(_request(_call(wording=_WORDING)),))

    assert export.schema_version == 28
    assert PlanExport.model_validate_json(export.model_dump_json()) == export
    with pytest.raises(ValidationError):
        PlanExport.model_validate({**export.model_dump(mode="json"), "schema_version": 27})
