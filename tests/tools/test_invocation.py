"""`tools/`'s own invocation rules, beside the code they constrain.

The shared conformance suite covers everything ``invoke`` is observably
required to do. What is here is what only *this* implementation can be held to:
the callable half of the registration lifecycle (deliberately off both
Protocols, ADR-0016 §5), and the message-leak rule's second half — that the
seam's **log** carries no content the seam did not author, which a suite cannot
assert about a fake that does not log.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
import structlog
from tool_invoker_contract import (
    BRIEF,
    PATIENT,
    Raiser,
    Spy,
    call_for,
    completions,
    natural,
    read_only,
    tool,
)

from ai_assistant.core.errors import ToolRegistrationError, TransportError
from ai_assistant.core.protocols import ToolInvoker, ToolRegistry
from ai_assistant.core.types import ToolFailureKind, ToolOutcome
from ai_assistant.testing import FakeAuditTrail, authorised, succeeds
from ai_assistant.tools.egress import IndeterminateTransmissionError
from ai_assistant.tools.registry import InMemoryToolRegistry, checked_timeout

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import FrozenJson, ToolDefinition, ToolResult


def test_one_object_presents_both_faces() -> None:
    """ADR-0029 §1: not two objects that happen to agree."""
    registry = InMemoryToolRegistry(ledger=FakeAuditTrail(), gate=FakeAuditTrail())

    assert isinstance(registry, ToolRegistry)
    assert isinstance(registry, ToolInvoker)


# --- registration binds a callable, and rebinding it is refused ---------


async def test_re_registering_the_same_definition_and_callable_is_idempotent() -> None:
    """So a composition root may run twice without special-casing."""
    registry = InMemoryToolRegistry(
        [(tool(), succeeds)], ledger=FakeAuditTrail(), gate=FakeAuditTrail()
    )

    registry.register(tool(), succeeds)

    assert len(await registry.all_tools()) == 1


async def test_rebinding_a_different_callable_under_a_bound_id_is_refused() -> None:
    """The declaration would still read as the one approved while different code
    ran behind it — the failure ADR-0016 §7 names, one level below the
    declaration.
    """
    original = Spy()
    trail = FakeAuditTrail()
    registry = InMemoryToolRegistry([(tool(), original)], ledger=trail, gate=trail)

    with pytest.raises(ToolRegistrationError, match="implementation"):
        registry.register(tool(), Spy())

    await registry.invoke(await authorised(trail, call_for(tool())), timeout=PATIENT)
    assert len(original.calls) == 1, "the original callable is still the bound one"


async def test_a_deregistered_tool_is_no_longer_invocable() -> None:
    """The biconditional holds in both directions across revocation."""
    registry = InMemoryToolRegistry(
        [(tool(), Spy())], ledger=FakeAuditTrail(), gate=FakeAuditTrail()
    )

    registry.deregister("smtp")

    assert await registry.all_tools() == []
    with pytest.raises(Exception, match="not bound"):
        await registry.invoke(call_for(tool()), timeout=PATIENT)


# --- the message-leak rule's log half (ADR-0029 §3) ---------------------


async def test_the_seams_log_carries_no_content_the_seam_did_not_author() -> None:
    """``core/logging.py`` redacts by *key* and names ``error=str(exc)`` as the
    Tier 1 leak it cannot see. Nothing downstream would catch this, so an
    untested rule here is an unenforced one.
    """
    trail = FakeAuditTrail()
    registry = InMemoryToolRegistry(
        [(tool(), Raiser(RuntimeError("recipient alice@example.com rejected")))],
        ledger=trail,
        gate=trail,
    )

    with structlog.testing.capture_logs() as logs:
        result = await registry.invoke(await authorised(trail, call_for(tool())), timeout=PATIENT)

    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.INTERNAL
    assert logs, "a broken integration is worth a log line"
    rendered = repr(logs)
    assert "alice@example.com" not in rendered
    assert "rejected" not in rendered
    assert "RuntimeError" in rendered


# --- the helper the seam is built from ----------------------------------
#
# The interrupted-call rule used to be tested here as a second `tools/`
# function. It is now `ToolDefinition.interrupted_outcome` (ADR-0031 §1) and its
# exhaustive table lives beside the type, in `tests/core/test_tool_types.py`.
# The seam keeps its *behavioural* tests — §10's "the timeout rule in §4 in both
# directions" is a statement about `invoke`, and it stays where one is observable
# (the shared conformance suite).


@pytest.mark.parametrize("bad", [timedelta(0), timedelta(seconds=-1), None, 5, "30s"])
def test_a_timeout_that_is_not_a_positive_timedelta_is_refused(bad: object) -> None:
    """The guard is total over the value, because the annotation is not."""
    with pytest.raises(ValueError, match="timeout"):
        checked_timeout(bad)


def test_a_positive_timeout_passes_through() -> None:
    assert checked_timeout(timedelta(seconds=1)) == timedelta(seconds=1)


# --- an indeterminate transmission is not a refusal (#1602) -------------
#
# The window `IndeterminateTransmissionError` marks is `tools/`-internal: the
# type is the egress seam's, so no shared conformance suite can require the
# canonical fake to know it, and the classification lives here with the
# implementation that does. Nothing outside `tests/tools/test_egress*` mentioned
# the type before this, which is exactly why the flattening survived every gate.


def indeterminate() -> IndeterminateTransmissionError:
    """The seam's own raise, worded as `_SmtpSession.data` words it."""
    return IndeterminateTransmissionError(
        "smtp: the message reached the transport and the endpoint's verdict could "
        "not be read, so whether it was accepted is unknown"
    )


async def invoked(definition: ToolDefinition, exc: BaseException) -> tuple[ToolResult, list[Any]]:
    """Invoke a tool that raises ``exc``, and hand back the result and the log."""
    trail = FakeAuditTrail()
    registry = InMemoryToolRegistry([(definition, Raiser(exc))], ledger=trail, gate=trail)
    call = await authorised(trail, call_for(definition))

    with structlog.testing.capture_logs() as logs:
        result = await registry.invoke(call, timeout=PATIENT)

    return result, logs


async def test_an_indeterminate_transmission_is_not_recorded_as_a_refusal() -> None:
    """ADR-0191 §4's last clause: nothing "permits such a failure to be recorded
    as a refusal that transmitted nothing". Before #1602 this came back
    ``FAILED``/``INTERNAL`` — the payload was on the wire and the user was told
    nothing went out.
    """
    trail = FakeAuditTrail()
    definition = tool()
    registry = InMemoryToolRegistry(
        [(definition, Raiser(indeterminate()))], ledger=trail, gate=trail
    )

    result = await registry.invoke(await authorised(trail, call_for(definition)), timeout=PATIENT)

    assert result.outcome is ToolOutcome.INDETERMINATE
    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.UNAVAILABLE


async def test_the_completion_row_records_the_indeterminate_outcome() -> None:
    """ADR-0192 §4's rendering reads the row, not the result: a completion saying
    ``FAILED`` is what an operator resolving this attempt would have been shown.
    """
    trail = FakeAuditTrail()
    definition = tool()
    registry = InMemoryToolRegistry(
        [(definition, Raiser(indeterminate()))], ledger=trail, gate=trail
    )

    await registry.invoke(await authorised(trail, call_for(definition)), timeout=PATIENT)

    completed = await completions(trail)
    assert [each.outcome for each in completed] == [ToolOutcome.INDETERMINATE]
    assert [each.failure_kind for each in completed] == [ToolFailureKind.UNAVAILABLE]
    assert await trail.open_invocations(decision_id="d-1") == [], "the claim is closed, not left"


async def test_the_failure_says_neither_that_it_was_sent_nor_that_it_was_not() -> None:
    """The entire content of this result is that the seam cannot say which, so a
    message asserting either half is the defect wearing a new outcome.
    """
    result, _ = await invoked(tool(), indeterminate())

    assert result.failure is not None
    message = result.failure.message
    assert "sent" not in message
    assert "nothing went out" not in message
    assert "unknown" in message


async def test_the_indeterminate_log_line_names_the_type_and_nothing_the_tool_wrote() -> None:
    """``core/logging.py`` redacts by key and cannot see ``error=str(exc)``. The
    seam's own text for this window names an endpoint, so it is not copied out.
    """
    raised = IndeterminateTransmissionError("smtp: carol@example.net may have received this")

    _, logs = await invoked(tool(), raised)

    assert [each["event"] for each in logs] == ["tool_transmission_indeterminate"], (
        "its own event, not the broken-integration one: an operator filtering for "
        "a tool that raised should not find a tool that did what it was ruled to do"
    )
    assert [each["error_type"] for each in logs] == ["IndeterminateTransmissionError"]
    rendered = repr(logs)
    assert "carol@example.net" not in rendered
    assert "may have received" not in rendered


@pytest.mark.parametrize("definition", [read_only(), natural()])
async def test_a_tool_that_leaves_nothing_unknown_is_failed_rather_than_indeterminate(
    definition: ToolDefinition,
) -> None:
    """The branch reads ``ToolDefinition.interrupted_outcome``, so it is right for
    every declaration rather than for ``send_email``'s. A read and a naturally
    idempotent act leave nothing for a reconciliation path to resolve (ADR-0029
    §4), and a literal ``INDETERMINATE`` here would send both to one.
    """
    result, _ = await invoked(definition, indeterminate())

    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.UNAVAILABLE


async def test_a_transport_failure_before_the_terminator_is_still_a_plain_failure() -> None:
    """The split the seam draws survives out here. Every ``EgressTransportError``
    is a refusal that provably transmitted nothing, and so is a bare
    ``TransportError``; widening the new branch to either would report an
    unknown disclosure for a call that certainly did not make one.
    """
    result, _ = await invoked(tool(), TransportError("the connection to smtp.example.com failed"))

    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.INTERNAL


async def test_the_seams_own_expiry_still_outranks_a_tool_that_absorbed_it() -> None:
    """`_interruption` runs ahead of this branch, because it is what re-raises a
    pending external cancellation — and a tool that converts the deadline's own
    cancellation into an indeterminate raise must not take the seam's expiry off
    the record. Both answers carry ``interrupted_outcome``, so what is at stake
    is which one is named, not the outcome.
    """
    trail = FakeAuditTrail()
    definition = tool()

    async def absorbs(
        parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise indeterminate() from None
        return None

    registry = InMemoryToolRegistry([(definition, absorbs)], ledger=trail, gate=trail)

    result = await registry.invoke(await authorised(trail, call_for(definition)), timeout=BRIEF)

    assert result.outcome is ToolOutcome.INDETERMINATE
    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.TIMED_OUT
