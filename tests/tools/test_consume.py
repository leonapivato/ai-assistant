"""The consume's `tools/`-internal half (ADR-0192 §1, §3, §5).

The shared conformance suite covers everything the consume is observably
required to do through ``invoke``, on both implementations. What is here is what
only *this* one can be held to, or what ``invoke``'s own surface cannot reach:

* the **callable-shape pairing check's ordering against the claim**. Which
  callable a declaration binds is `tools/`-internal and contracted nowhere
  (ADR-0152 §10), and the canonical fake binds one shape, so this check exists
  here alone — and ADR-0192 §1 moves it **above** the claim rather than leaving
  it where an implementation happened to have put it.
* the ``ToolResult`` → ``ToolInvocation`` **cost mapping** for a result that
  carries a figure. Nothing populates ``ToolResult.incurred_cost`` yet (#1558),
  so no call through ``invoke`` can produce one; the mapping is driven at
  :func:`~ai_assistant.tools.consume.consumed_call`, which is the boundary
  ADR-0192 §5 actually decides.
* that the two copies of the diagnostic's enumerated field values — this
  subsystem's and the canonical fake's — have not drifted apart.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from egress_transport_harness import arguments, binding
from tool_invoker_contract import PATIENT, DrivenLedger, Spy, call_for, rows, tool

from ai_assistant.core.errors import ToolBindingError
from ai_assistant.core.types import (
    ActionRequest,
    CostBasis,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ToolCall,
    ToolCost,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.testing import FakeAuditTrail
from ai_assistant.testing import invoker as fake_invoker
from ai_assistant.tools import consume
from ai_assistant.tools.registry import InMemoryToolRegistry

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import EgressBinding, FrozenJson

AT = call_for(tool()).decision.decided_at


class BoundSpy:
    """An **egress** callable: it takes the binding the ruling fixed (ADR-0148 §4)."""

    def __init__(self) -> None:
        """Record nothing yet."""
        self.calls: list[EgressBinding] = []

    async def invoke_bound(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
        egress_binding: EgressBinding,
    ) -> FrozenJson:
        """Record the binding it was handed and succeed."""
        self.calls.append(egress_binding)
        return None


def call_carrying(definition: object, bound: EgressBinding | None) -> ToolCall:
    """An authorised call for ``definition``, carrying ``bound`` or nothing.

    The parameters are the harness's, so a binding's spans name arguments the
    call actually carries — the invariant ``ActionRequest`` enforces, which is
    beside the point here and would otherwise decide the case before the seam
    saw it.
    """
    request = ActionRequest(
        tool=definition,  # type: ignore[arg-type]  # the builder's own type
        parameters=arguments(),
        step_id="step-1",
        egress_binding=bound,
    )
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="because it is allow"),
        id="d-1",
        decided_at=AT,
    )
    return ToolCall(request=request, decision=decision)


@pytest.mark.parametrize("shape", ["egress-callable-without-a-binding", "plain-callable-with-one"])
async def test_the_pairing_check_refuses_before_any_claim_is_appended(shape: str) -> None:
    """ADR-0192 §1's floor is not the whole ordering, and this is the check it adds.

    An implementation claiming first passes every other case in the suite and
    then owes ADR-0192 §3 a completion carrying an outcome ADR-0029 computes for
    no ``ToolBindingError`` — that error is given no ``ToolResult`` at all, only
    the executor's ``FAILED`` step. So the trail holds no invocation row for that
    decision afterwards, the callable is never entered, and no completion is
    attempted.
    """
    trail = FakeAuditTrail()
    ledger = DrivenLedger(trail)
    if shape == "egress-callable-without-a-binding":
        implementation: object = BoundSpy()
        call = call_carrying(tool(), None)
    else:
        implementation = Spy()
        call = call_carrying(tool(), binding())
    registry = InMemoryToolRegistry([(tool(), implementation)], ledger=ledger)  # type: ignore[list-item]  # the doubles' own shapes
    await trail.record(call.decision)

    with pytest.raises(ToolBindingError):
        await registry.invoke(call, timeout=PATIENT)

    assert implementation.calls == [], "the callable is never entered"  # type: ignore[attr-defined]
    assert ledger.claim.calls == 0, "no claim is appended for a seam fault"
    assert ledger.completion.calls == 0
    assert await rows(trail) == []


async def test_a_reported_cost_maps_onto_the_row_unaltered() -> None:
    """ADR-0192 §5's boundary, driven where the mapping actually is.

    Not through ``invoke``: ``ToolImplementation`` returns ``FrozenJson`` and no
    ADR owns minting a carrier, so a case asserting a figure traversing the
    production path would have to construct a ``ToolResult`` past the seam or
    patch inside it — proving the mapping this drives and proving nothing about
    the path. The end-to-end case is owed by whichever ADR answers #1558.
    """
    trail = FakeAuditTrail()
    call = call_for(tool())
    await trail.record(call.decision)
    reported = ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.02"), currency="USD")

    async def act() -> ToolResult:
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, incurred_cost=reported)

    await consume.consumed_call(ledger=trail, definition=tool(), decision=call.decision, act=act)

    (completion,) = [each for each in await rows(trail) if each.completes is not None]
    assert completion.incurred_cost == reported


def test_the_two_copies_of_the_diagnostics_vocabulary_agree() -> None:
    """The fake re-implements the consume, so the enumerated values are duplicated.

    They are the fields an operator's alerting keys on, and a drift between the
    two would be invisible to every behavioural case in the suite: each
    implementation would report its own vocabulary consistently.
    """
    assert (consume.CLAIM, consume.COMPLETION, consume.APPEND_FAILED) == (
        fake_invoker.CLAIM,
        fake_invoker.COMPLETION,
        fake_invoker.APPEND_FAILED,
    )
