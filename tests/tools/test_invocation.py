"""`tools/`'s own invocation rules, beside the code they constrain.

The shared conformance suite covers everything ``invoke`` is observably
required to do. What is here is what only *this* implementation can be held to:
the callable half of the registration lifecycle (deliberately off both
Protocols, ADR-0016 §5), and the message-leak rule's second half — that the
seam's **log** carries no content the seam did not author, which a suite cannot
assert about a fake that does not log.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
import structlog
from tool_invoker_contract import PATIENT, Raiser, Spy, call_for, natural, read_only, tool

from ai_assistant.core.errors import ToolRegistrationError
from ai_assistant.core.protocols import ToolInvoker, ToolRegistry
from ai_assistant.core.types import ToolFailureKind, ToolOutcome
from ai_assistant.testing import succeeds
from ai_assistant.tools.invocation import interrupted_outcome
from ai_assistant.tools.registry import InMemoryToolRegistry, checked_timeout


def test_one_object_presents_both_faces() -> None:
    """ADR-0029 §1: not two objects that happen to agree."""
    registry = InMemoryToolRegistry()

    assert isinstance(registry, ToolRegistry)
    assert isinstance(registry, ToolInvoker)


# --- registration binds a callable, and rebinding it is refused ---------


async def test_re_registering_the_same_definition_and_callable_is_idempotent() -> None:
    """So a composition root may run twice without special-casing."""
    registry = InMemoryToolRegistry([(tool(), succeeds)])

    registry.register(tool(), succeeds)

    assert len(await registry.all_tools()) == 1


async def test_rebinding_a_different_callable_under_a_bound_id_is_refused() -> None:
    """The declaration would still read as the one approved while different code
    ran behind it — the failure ADR-0016 §7 names, one level below the
    declaration.
    """
    original = Spy()
    registry = InMemoryToolRegistry([(tool(), original)])

    with pytest.raises(ToolRegistrationError, match="implementation"):
        registry.register(tool(), Spy())

    await registry.invoke(call_for(tool()), timeout=PATIENT)
    assert len(original.calls) == 1, "the original callable is still the bound one"


async def test_a_deregistered_tool_is_no_longer_invocable() -> None:
    """The biconditional holds in both directions across revocation."""
    registry = InMemoryToolRegistry([(tool(), Spy())])

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
    registry = InMemoryToolRegistry(
        [(tool(), Raiser(RuntimeError("recipient alice@example.com rejected")))]
    )

    with structlog.testing.capture_logs() as logs:
        result = await registry.invoke(call_for(tool()), timeout=PATIENT)

    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.INTERNAL
    assert logs, "a broken integration is worth a log line"
    rendered = repr(logs)
    assert "alice@example.com" not in rendered
    assert "rejected" not in rendered
    assert "RuntimeError" in rendered


# --- the two helpers the seam is built from -----------------------------


@pytest.mark.parametrize(
    ("definition", "expected"),
    [
        (tool(), ToolOutcome.INDETERMINATE),
        (read_only(), ToolOutcome.FAILED),
        (natural(), ToolOutcome.FAILED),
    ],
    ids=["side-effecting", "read-only", "natural"],
)
def test_the_interrupted_call_rule_is_one_function(definition: object, expected: object) -> None:
    """Stated once, so the timeout branch and any future caller cannot diverge."""
    assert interrupted_outcome(definition) is expected  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [timedelta(0), timedelta(seconds=-1), None, 5, "30s"])
def test_a_timeout_that_is_not_a_positive_timedelta_is_refused(bad: object) -> None:
    """The guard is total over the value, because the annotation is not."""
    with pytest.raises(ValueError, match="timeout"):
        checked_timeout(bad)


def test_a_positive_timeout_passes_through() -> None:
    assert checked_timeout(timedelta(seconds=1)) == timedelta(seconds=1)
