"""ADR-0306 §2 and §6's `core` types: the five declaration fields and acting's records.

Covers what a capability declares on ``ToolDefinition`` and the two validators that
bind it to the declaration's other fields (§2:5 as ADR-0312 §2 corrects it, and
§2:6); ``ActivationEffect``'s call-or-message shape and its outcome fields;
``PermissionDecision.effect``, which ``from_request`` transcribes and ``authorises``
does not compare; and ``PlanExport.activation_effects``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ActionRequest,
    ActivationEffect,
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    DataTier,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanExport,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
)

_AT: Final = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def _fields(**overrides: Any) -> dict[str, Any]:
    """A read that stays in the hub, with every field a test varies spelled out."""
    fields: dict[str, Any] = {
        "id": "lookup",
        "capability": "lookup",
        "description": "Look something up.",
        "risk_level": RiskLevel.LOW,
        "reversibility": Reversibility.REVERSIBLE,
        "side_effecting": False,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NATURAL,
        "effect": CapabilityEffect.NONE,
        "leaves_hub": False,
        "result": CapabilityResult.NO_OUTSIDE_TEXT,
        "outcome_can_be_unknown": False,
        "safe_to_repeat": True,
    }
    fields.update(overrides)
    return fields


#: The web search's shape: it discloses the query, writes nothing, and changes nothing.
_SEARCH: Final = {
    "side_effecting": True,
    "discloses": (DataTier.PERSONAL,),
    "idempotency": Idempotency.NONE,
    "leaves_hub": True,
    "result": CapabilityResult.MAY_CARRY_OUTSIDE_TEXT,
    "outcome_can_be_unknown": True,
}


@pytest.mark.parametrize(
    "missing",
    ["effect", "leaves_hub", "result", "outcome_can_be_unknown", "safe_to_repeat"],
)
def test_each_of_the_five_is_required(missing: str) -> None:
    """§2:2: all five are required, with no default."""
    fields = _fields()
    del fields[missing]

    with pytest.raises(ValidationError, match=missing):
        ToolDefinition(**fields)


@pytest.mark.parametrize("effect", [CapabilityEffect.OWN_RECORDS, CapabilityEffect.WORLD])
def test_an_effect_requires_side_effecting(effect: CapabilityEffect) -> None:
    """§2:5, ADR-0312 §2:1: an effect that is not none on a non-side-effecting tool."""
    with pytest.raises(ValidationError, match="side-effecting"):
        ToolDefinition(**_fields(effect=effect))


def test_a_tool_that_only_discloses_may_declare_no_effect() -> None:
    """ADR-0312 §2:2: side-effecting with no effect, where the one side effect is disclosure."""
    search = ToolDefinition(**_fields(**_SEARCH))

    assert search.effect is CapabilityEffect.NONE
    assert search.interrupted_outcome is ToolOutcome.INDETERMINATE


@pytest.mark.parametrize(
    "shape",
    [
        {"writes": (DataTier.PERSONAL,)},
        {"discloses": ()},
    ],
    ids=["writes", "discloses-nothing"],
)
def test_a_side_effecting_tool_with_no_effect_must_only_disclose(
    shape: dict[str, Any],
) -> None:
    """ADR-0312 §2:2: no effect on a side-effecting tool that writes, or discloses nothing."""
    with pytest.raises(ValidationError, match="ADR-0312"):
        ToolDefinition(**_fields(**{**_SEARCH, **shape}))


def test_an_indeterminate_interruption_declares_an_unknown_outcome() -> None:
    """§2:6: never unknown, not own records, and interrupted indeterminate: refused."""
    with pytest.raises(ValidationError, match="unknown"):
        ToolDefinition(**_fields(**{**_SEARCH, "outcome_can_be_unknown": False}))


def test_a_call_on_the_assistants_own_records_is_never_unknown() -> None:
    """§2:6 and §3:3: own records are awaited to their end, so never unknown."""
    remember = ToolDefinition(
        **_fields(
            side_effecting=True,
            writes=(DataTier.PERSONAL,),
            idempotency=Idempotency.NONE,
            effect=CapabilityEffect.OWN_RECORDS,
            result=CapabilityResult.NONE,
            safe_to_repeat=False,
        )
    )

    assert remember.interrupted_outcome is ToolOutcome.INDETERMINATE
    assert remember.outcome_can_be_unknown is False


def test_the_five_survive_a_round_trip() -> None:
    """A recorded decision reloads its declaration whole (ADR-0021 §4)."""
    search = ToolDefinition(**_fields(**_SEARCH))

    assert ToolDefinition.model_validate_json(search.model_dump_json()) == search


# --- ActivationEffect -----------------------------------------------------------


def _call(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "id": "e1",
        "activation_id": "act-1",
        "round": "r1",
        "capability": "book_stay",
        "values_digest": "a" * 64,
        "decision_id": "d1",
        "claimed_at": _AT,
    }
    fields.update(overrides)
    return fields


def _message(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "id": "m1",
        "activation_id": "act-1",
        "round": "r1",
        "place": "c-1",
        "claimed_at": _AT,
    }
    fields.update(overrides)
    return fields


def test_a_call_and_a_message_are_each_whole() -> None:
    """§6: a call carries its capability, values and decision; a message its place."""
    call = ActivationEffect(**_call())
    message = ActivationEffect(**_message())

    assert call.is_call
    assert not message.is_call
    assert message.round == "r1"


@pytest.mark.parametrize(
    "fields",
    [
        _call(values_digest=None),
        _call(decision_id=None),
        _call(place="c-1"),
        _call(round=None),
        _message(place=None),
        _message(decision_id="d1"),
        _message(values_digest="a" * 64),
    ],
    ids=[
        "call-without-values",
        "call-without-decision",
        "call-with-place",
        "call-without-round",
        "message-without-place",
        "message-with-decision",
        "message-with-values",
    ],
)
def test_a_record_that_is_neither_whole_is_refused(fields: dict[str, Any]) -> None:
    """§6 and ADR-0307 §10: never both, never neither, and a call names its round."""
    with pytest.raises(ValidationError):
        ActivationEffect(**fields)


def test_only_the_couldnt_finish_message_names_no_round() -> None:
    """ADR-0307 §10: ``round`` is ``None`` only on a message."""
    assert ActivationEffect(**_message(round=None)).round is None


@pytest.mark.parametrize(
    "fields",
    [
        _call(outcome=ToolOutcome.SUCCEEDED, reason="no"),
        _call(outcome=ToolOutcome.INDETERMINATE, reason="no"),
        _call(reason="no"),
        _message(outcome=ToolOutcome.FAILED, position=2),
        _message(position=2),
        _call(outcome=ToolOutcome.SUCCEEDED, position=2),
    ],
    ids=[
        "reason-on-done",
        "reason-on-unknown",
        "reason-unfinished",
        "position-on-message-not-done",
        "position-unfinished",
        "position-on-call",
    ],
)
def test_the_reason_and_position_belong_to_their_outcome(fields: dict[str, Any]) -> None:
    """§5:5, §6:4: a reason only on not done, a position only on a message done."""
    with pytest.raises(ValidationError):
        ActivationEffect(**fields)


def test_a_finished_record_carries_its_outcome() -> None:
    """A done message carries its position; a call not done its reason."""
    message = ActivationEffect(**_message(outcome=ToolOutcome.SUCCEEDED, position=4))
    call = ActivationEffect(**_call(outcome=ToolOutcome.FAILED, reason="refused"))

    assert (message.position, call.reason) == (4, "refused")


# --- PermissionDecision.effect ----------------------------------------------------


def _request() -> ActionRequest:
    return ActionRequest(tool=ToolDefinition(**_fields()))


def test_from_request_sets_the_effect_the_recorder_supplies() -> None:
    """§6: minted before the ruling and set by the recorder, like ``id``."""
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="fine")

    decision = PermissionDecision.from_request(
        _request(), ruling, id="d1", decided_at=_AT, effect="e1"
    )

    assert decision.effect == "e1"
    assert PermissionDecision.model_validate_json(decision.model_dump_json()) == decision


def test_the_effect_defaults_to_none() -> None:
    """Every decision of the old path, and every call with no record, carries none."""
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="fine")

    assert PermissionDecision.from_request(_request(), ruling, id="d1", decided_at=_AT).effect is (
        None
    )


def test_authorises_does_not_compare_the_effect() -> None:
    """§6: ``authorises`` answers the same whatever the effect names."""
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="fine")
    request = _request()

    with_effect = PermissionDecision.from_request(
        request, ruling, id="d1", decided_at=_AT, effect="e1"
    )
    without = PermissionDecision.from_request(request, ruling, id="d1", decided_at=_AT)

    assert with_effect.authorises(request)
    assert without.authorises(request)


# --- PlanExport.activation_effects -------------------------------------------------


def test_the_export_carries_activation_effects_once_each() -> None:
    """§6: the document carries the records, and no id twice."""
    record = ActivationEffect(**_call())

    export = PlanExport(exported_at=_AT, activation_effects=(record,))
    assert PlanExport.model_validate_json(export.model_dump_json()) == export

    with pytest.raises(ValidationError, match="duplicate activation effect"):
        PlanExport(exported_at=_AT, activation_effects=(record, record))
