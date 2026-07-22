"""The invocation types enforce what ADR-0029 §2, §3 and §5 say they enforce.

These are the claims that hold for *every* ``ToolInvoker`` by construction, so
they are pinned here rather than in the shared conformance suite: a suite exists
to catch what implementations can differ on, and no implementation can vary what
a frozen `core` model refuses to be.

Most of them pin a **rejection**. Annotations cannot express a cross-field rule
and a comment beside a field does not enforce one, so each combination an
annotation alone would permit gets a test that it does not survive construction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ActionRequest,
    CostBasis,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    ToolCall,
    ToolCost,
    ToolDefinition,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import FrozenJson

AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def tool(**overrides: Any) -> ToolDefinition:
    """Build a valid, side-effecting definition."""
    fields: dict[str, object] = {
        "id": "smtp",
        "capability": "send_email",
        "description": "Send an email.",
        "risk_level": RiskLevel.HIGH,
        "reversibility": Reversibility.IRREVERSIBLE,
        "side_effecting": True,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NONE,
    }
    fields.update(overrides)
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def request_for(
    definition: ToolDefinition | None = None,
    *,
    parameters: Mapping[str, FrozenJson] | None = None,
    step_id: str | None = "step-1",
) -> ActionRequest:
    """Build a request about ``definition``."""
    return ActionRequest(
        tool=definition or tool(),
        parameters=parameters or {"to": "someone@example.com"},
        step_id=step_id,
    )


def decision_for(
    request: ActionRequest,
    outcome: PermissionOutcome = PermissionOutcome.ALLOW,
    *,
    decision_id: str = "d-1",
) -> PermissionDecision:
    """Bind a ruling to ``request`` through the sanctioned construction path."""
    return PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=outcome, reason=f"because it is {outcome}"),
        id=decision_id,
        decided_at=AT,
    )


# --- §2: an unauthorised call is unconstructable ------------------------


def test_an_allow_for_this_request_constructs() -> None:
    """The control: the refusals below are not failing for free."""
    request = request_for()

    call = ToolCall(request=request, decision=decision_for(request))

    assert call.request is request


@pytest.mark.parametrize(
    "outcome",
    [PermissionOutcome.DENY, PermissionOutcome.CONFIRM],
    ids=["deny", "unanswered-confirm"],
)
def test_a_call_without_an_allow_is_unconstructable(outcome: PermissionOutcome) -> None:
    """A refusal authorises nothing, and a question is not an answer.

    The ``CONFIRM`` case is the one worth being explicit about: it is a decision
    that exists and is recorded, so a caller could reasonably mistake having one
    for having permission.
    """
    request = request_for()

    with pytest.raises(ValidationError, match="does not authorise"):
        ToolCall(request=request, decision=decision_for(request, outcome))


def test_altered_parameters_make_the_call_unconstructable() -> None:
    """Authorising an email to one recipient must not execute it to another."""
    approved = request_for(parameters={"to": "approved@example.com"})
    decision = decision_for(approved)

    with pytest.raises(ValidationError, match="does not authorise"):
        ToolCall(request=request_for(parameters={"to": "elsewhere@example.com"}), decision=decision)


def test_a_substituted_definition_makes_the_call_unconstructable() -> None:
    """The decision pins the whole declaration, so a downgrade is a mismatch."""
    decision = decision_for(request_for(tool(risk_level=RiskLevel.CRITICAL)))

    with pytest.raises(ValidationError, match="does not authorise"):
        ToolCall(request=request_for(tool(risk_level=RiskLevel.LOW)), decision=decision)


def test_a_mismatched_step_id_makes_the_call_unconstructable() -> None:
    """An approval belongs to the step it was asked about."""
    decision = decision_for(request_for(step_id="step-1"))

    with pytest.raises(ValidationError, match="does not authorise"):
        ToolCall(request=request_for(step_id="step-2"), decision=decision)


def test_a_tool_call_forbids_extra_fields() -> None:
    """No credential, no timeout, no key: anything a caller could fill in is a
    field a caller could fill in wrongly (ADR-0029 §2, §6).
    """
    request = request_for()

    with pytest.raises(ValidationError):
        ToolCall(request=request, decision=decision_for(request), timeout=timedelta(seconds=1))  # type: ignore[call-arg]


# --- §5: the key is derived, not minted ---------------------------------


def test_a_keyed_tool_derives_its_key_from_the_decision() -> None:
    request = request_for(tool(idempotency=Idempotency.KEYED, idempotency_window=timedelta(days=1)))

    call = ToolCall(request=request, decision=decision_for(request, decision_id="d-42"))

    assert call.idempotency_key == "d-42"


@pytest.mark.parametrize("guarantee", [Idempotency.NONE, Idempotency.NATURAL])
def test_a_tool_that_is_not_keyed_has_no_key(guarantee: Idempotency) -> None:
    request = request_for(tool(idempotency=guarantee))

    call = ToolCall(request=request, decision=decision_for(request))

    assert call.idempotency_key is None


# --- §3: retryable is a property of the kind ----------------------------


def test_retryable_is_declared_for_every_failure_kind() -> None:
    """Exhaustive rather than sampled, so a member added later cannot default
    silently — it raises instead, which is the mistake being loud.
    """
    expected = {
        ToolFailureKind.INVALID_REQUEST: False,
        ToolFailureKind.NOT_AUTHORISED: False,
        ToolFailureKind.UNAVAILABLE: True,
        ToolFailureKind.RATE_LIMITED: True,
        ToolFailureKind.TIMED_OUT: True,
        ToolFailureKind.CANCELLED: True,
        ToolFailureKind.REFUSED: False,
        ToolFailureKind.INTERNAL: False,
    }

    assert set(expected) == set(ToolFailureKind), "a new kind needs a retryable value here"
    assert {kind: kind.retryable for kind in ToolFailureKind} == expected


# --- §3: the result's cross-field invariants ----------------------------


def test_a_successful_result_constructs() -> None:
    """The control for the four rejections below."""
    result = ToolResult(outcome=ToolOutcome.SUCCEEDED, output={"id": "m-1"})

    assert result.failure is None
    assert result.output == {"id": "m-1"}


@pytest.mark.parametrize("outcome", [ToolOutcome.FAILED, ToolOutcome.INDETERMINATE])
def test_a_non_successful_result_requires_a_failure(outcome: ToolOutcome) -> None:
    """Otherwise the executor writes ``StepExecution.error`` with nothing to write."""
    with pytest.raises(ValidationError, match="requires a failure"):
        ToolResult(outcome=outcome)


def test_a_successful_result_carrying_a_failure_is_refused() -> None:
    """A contradiction a caller reads whichever half it looks at first."""
    with pytest.raises(ValidationError, match="carries no failure"):
        ToolResult(
            outcome=ToolOutcome.SUCCEEDED,
            failure=ToolFailure(kind=ToolFailureKind.INTERNAL, message="boom"),
        )


@pytest.mark.parametrize("outcome", [ToolOutcome.FAILED, ToolOutcome.INDETERMINATE])
def test_a_non_successful_result_carrying_an_output_is_refused(outcome: ToolOutcome) -> None:
    """A partial result stored as a whole one is worse than an absent one."""
    with pytest.raises(ValidationError, match="carries no output"):
        ToolResult(
            outcome=outcome,
            output={"partial": True},
            failure=ToolFailure(kind=ToolFailureKind.TIMED_OUT, message="too slow"),
        )


def test_the_refusal_message_never_quotes_the_output() -> None:
    """A ``ValidationError`` is bound for a log the redactor cannot see into."""
    with pytest.raises(ValidationError) as caught:
        ToolResult(
            outcome=ToolOutcome.FAILED,
            output={"to": "alice@example.com"},
            failure=ToolFailure(kind=ToolFailureKind.TIMED_OUT, message="too slow"),
        )

    assert "alice@example.com" not in str(caught.value)


@pytest.mark.parametrize("blank", ["", "   ", "\u200b\ufe0f"], ids=["empty", "spaces", "invisible"])
def test_a_failure_message_that_renders_as_nothing_is_refused(blank: str) -> None:
    """A failure that renders as nothing leaves the user with nothing to say
    about it — the ``_has_visible_text`` test ADR-0018 §1 applies to a
    description and ADR-0021 §1 to a reason.
    """
    with pytest.raises(ValidationError, match="visible text"):
        ToolFailure(kind=ToolFailureKind.INTERNAL, message=blank)


def test_a_failure_message_is_stored_stripped() -> None:
    assert ToolFailure(kind=ToolFailureKind.REFUSED, message="  declined \n").message == "declined"


def test_a_result_round_trips_through_json() -> None:
    """``output`` lands in a durable ``StepExecution``, so it must survive the trip."""
    result = ToolResult(
        outcome=ToolOutcome.SUCCEEDED,
        output={"ids": ["m-1", "m-2"], "count": 2, "nested": {"ok": True}},
    )

    assert ToolResult.model_validate(result.model_dump(mode="json")) == result


def test_a_failed_result_round_trips_through_json() -> None:
    result = ToolResult(
        outcome=ToolOutcome.INDETERMINATE,
        failure=ToolFailure(kind=ToolFailureKind.TIMED_OUT, message="no answer in time"),
    )

    assert ToolResult.model_validate(result.model_dump(mode="json")) == result
