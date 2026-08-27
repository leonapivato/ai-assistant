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
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from _int_str_digits import pinned_int_str_digits
from pydantic import ValidationError

from ai_assistant.core.errors import AssistantError, ClassifiedToolError, ToolError
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


# --- ToolResult.output with no JSON encoding (issue #121, #409) -------------
# output is a FrozenJsonValue holder, matching StepExecution.output exactly, so
# it inherits _freeze_json's refusal of a value that satisfies its Python type
# but has no portable encoding. #401 pinned that for PlanStep.parameters and
# StepExecution.output; this carrier carries the same guarantee and had no
# field-specific regression until #409.


def test_a_successful_result_output_with_a_lone_surrogate_is_rejected() -> None:
    """A lone surrogate is a ``str`` with no UTF-8 encoding (ADR-0021 §1)."""
    with pytest.raises(ValidationError, match="no JSON encoding"):
        ToolResult(outcome=ToolOutcome.SUCCEEDED, output={"body": "\ud800"})


def test_a_successful_result_output_with_an_unrenderable_integer_is_rejected() -> None:
    """``json.dumps`` renders an int through ``str()``; CPython refuses one past
    its integer-string conversion limit, so the value has no JSON encoding.

    ``pinned_int_str_digits`` holds the limit at the default so ``10**5000``
    stays unrenderable under a raised or disabled ``PYTHONINTMAXSTRDIGITS``
    (#406)."""
    with pinned_int_str_digits(), pytest.raises(ValidationError, match="no JSON encoding"):
        ToolResult(outcome=ToolOutcome.SUCCEEDED, output={"n": 10**5000})


def test_an_ordinary_result_output_still_round_trips() -> None:
    """The bound is "can it be encoded", not "is it big" or "is it astral"."""
    result = ToolResult(
        outcome=ToolOutcome.SUCCEEDED,
        output={"n": 10**100, "emoji": "\U0001f389 done"},
    )

    assert ToolResult.model_validate(result.model_dump(mode="json")) == result


def test_a_scalar_result_output_is_accepted() -> None:
    """output is a single ``FrozenJsonValue``, not a mapping: a bare scalar is a
    valid output, so a regression narrowing the field to a mapping is caught.
    """
    result = ToolResult(outcome=ToolOutcome.SUCCEEDED, output="m-1")

    assert result.output == "m-1"
    assert ToolResult.model_validate(result.model_dump(mode="json")) == result


def test_a_scalar_result_output_with_a_lone_surrogate_is_rejected() -> None:
    """A bare scalar runs through ``_freeze_json`` too, so an unencodable scalar
    is refused — not only an unencodable value nested inside a mapping. Guards a
    regression that checks mapping values but admits a bare unencodable string.
    """
    with pytest.raises(ValidationError, match="no JSON encoding"):
        ToolResult(outcome=ToolOutcome.SUCCEEDED, output="\ud800")


# --- ADR-0032 §1: the carrier a tool classifies its own failure with ---------
#
# Type-level, so it belongs here rather than in the shared suite: no
# ``ToolInvoker`` can vary what an exception class's own constructor refuses.
# What the *seam* does with one is the suite's, and every clause of it is there.


def classified(
    kind: ToolFailureKind = ToolFailureKind.RATE_LIMITED,
    message: str = "the upstream throttled us",
    *,
    committed: bool = False,
    cost: ToolCost | None = None,
) -> ClassifiedToolError:
    """A carrier built the way an integration author writes one."""
    return ClassifiedToolError(
        ToolFailure(kind=kind, message=message),
        effect_may_have_committed=committed,
        incurred_cost=cost,
    )


def test_a_carrier_holds_the_three_values_it_was_given() -> None:
    """ADR-0032 §1 and ADR-0195 §3: a failure, a fact, and what the call cost."""
    price = ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.03"), currency="USD")

    error = classified(committed=True, cost=price)

    assert error.failure == ToolFailure(
        kind=ToolFailureKind.RATE_LIMITED, message="the upstream throttled us"
    )
    assert error.effect_may_have_committed is True
    assert error.incurred_cost == price


def test_the_effect_fact_is_required_and_keyword_only() -> None:
    """ADR-0032 §2: the raiser answers it explicitly, every time.

    Both candidate defaults are wrong in a direction, so ``core`` must not pick
    one on the author's behalf — ``False`` silently records a possibly-committed
    effect as certainly-nothing-happened, which is the one direction ADR-0014 §4
    refuses to guess in, and ``True`` floods the system with an ``INDETERMINATE``
    that is never auto-retried. The cost is a keyword on every raise, and it is
    the point: an author who has to type it has to think about it once per
    failure path.
    """
    failure = ToolFailure(kind=ToolFailureKind.REFUSED, message="the upstream declined it")

    with pytest.raises(TypeError):
        ClassifiedToolError(failure)  # type: ignore[call-arg]  # the point of this case
    with pytest.raises(TypeError):
        ClassifiedToolError(failure, True)  # type: ignore[call-arg]  # keyword-only, deliberately


def test_the_reported_cost_is_defaulted_and_keyword_only() -> None:
    """ADR-0195 §3: the asymmetry with the fact is argued rather than inherited.

    A defaulted ``None`` asserts "no figure", which is what silence already means
    everywhere else and is the fail-closed direction under ADR-0194 §2. Requiring
    it would break every raise site to make authors type the answer silence
    already gives.
    """
    failure = ToolFailure(kind=ToolFailureKind.UNAVAILABLE, message="the upstream is down")

    assert ClassifiedToolError(failure, effect_may_have_committed=False).incurred_cost is None
    with pytest.raises(TypeError):
        ClassifiedToolError(  # type: ignore[call-arg]  # keyword-only, deliberately
            failure, False, ToolCost(basis=CostBasis.FREE)
        )


def test_the_carrier_is_an_assistant_error_and_deliberately_not_a_tool_error() -> None:
    """ADR-0032 §1: the placement is load-bearing.

    ``ToolError``'s children are faults *the seam raises*, and ADR-0029 §8 spends
    a paragraph on why an executor must never derive a retry from one — "retry is
    scheduled only from a ``ToolResult``, never from an exception". ``except
    ToolError`` is a plausible line for an executor or an interface adapter to
    write, and it must not catch a carrier whose whole purpose is to *become* a
    result the executor may retry. Keeping it off that branch means the
    conflation is not available; ``AssistantError`` still holds it, so this
    module's stated invariant is preserved.
    """
    error = classified()

    assert isinstance(error, AssistantError)
    assert isinstance(error, Exception), "a BaseException would be swallowed by ADR-0029 §3"
    assert not isinstance(error, ToolError)
    assert not issubclass(ClassifiedToolError, ToolError)

    caught: BaseException | None = None
    try:
        raise classified()
    except ToolError as by_the_seams_branch:  # pragma: no cover - the point is that it misses
        caught = by_the_seams_branch
    except ClassifiedToolError:
        pass

    assert caught is None, "an executor's `except ToolError` must not catch the carrier"


def test_the_carrier_renders_as_nothing_and_carries_no_arguments() -> None:
    """ADR-0032 §5, made unbreakable-by-accident rather than merely forbidden.

    The seam may render nothing derived from this object — ``str()``, ``repr()``,
    ``args``, ``__cause__``, ``__context__``, ``__notes__`` — into a message or a
    log. A carrier holding no text of its own is the form in which that cannot be
    broken by an implementation reaching for the obvious diagnostic. What an
    operator reads is ``failure``, which the seam passes through by value.
    """
    error = classified(message="the upstream throttled us")

    assert error.args == ()
    assert str(error) == ""
    assert "throttled" not in repr(error)


def test_a_blank_message_fails_in_the_tools_own_frame_before_a_carrier_exists() -> None:
    """ADR-0032 §1: the validation happens where it is useful.

    ``ToolFailure._message_is_present`` fires at the raise site, in the tool
    author's own frame, so a blank message never gets as far as a carrier. That
    is the *ordinary* path and not a guarantee — ``model_construct`` bypasses
    every validator while still satisfying ``isinstance``, which is why ADR-0032
    §6 has the seam revalidate rather than trust the raise site, and why the
    suite pins both routes.
    """
    with pytest.raises(ValidationError, match="visible text"):
        classified(message="   ")


def test_a_cause_chain_stays_available_because_the_seam_renders_none_of_it() -> None:
    """``raise ClassifiedToolError(...) from upstream`` is good practice (§5).

    The chain is exactly what a developer wants in a traceback, and it is also
    where an upstream's error body lives — quoting a recipient or a subject line.
    Keeping it out of everything the seam renders is what makes ``from`` safe to
    write, and that half is pinned at the seam; here it is only that the chain is
    ordinary and available.
    """
    upstream = RuntimeError("recipient alice@example.com rejected")

    def integration() -> None:
        """What an integration author writes on a failure path it can classify."""
        try:
            raise upstream
        except RuntimeError as exc:
            raise classified() from exc

    with pytest.raises(ClassifiedToolError) as raised:
        integration()

    assert raised.value.__cause__ is upstream
    assert "alice@example.com" not in str(raised.value)
