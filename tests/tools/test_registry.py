"""`InMemoryToolRegistry`: the shared query contract, plus `tools/`'s own rules.

The registration invariants live here rather than in the shared conformance
suite, and that placement is the decision rather than an accident (ADR-0018 §4
and §5). Registration is deliberately off the `ToolRegistry` Protocol
(ADR-0016 §5) so `tools/` can change how it registers without moving a
cross-subsystem contract. `FakeToolRegistry` is importable by every subsystem,
so holding it to these rules would export that lifecycle in practice however the
prose described it.

So: the shared suite covers the four query methods, and everything below binds
this implementation only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError
from tool_registry_contract import ToolRegistryContract, tool

from ai_assistant.core.errors import ToolRegistrationError
from ai_assistant.core.types import Reversibility, RiskLevel
from ai_assistant.tools.registry import InMemoryToolRegistry

if TYPE_CHECKING:
    from tool_registry_contract import PopulatableToolRegistry


class TestInMemoryToolRegistryContract(ToolRegistryContract):
    """Runs InMemoryToolRegistry through the shared ToolRegistry conformance suite."""

    @pytest.fixture
    def registry(self) -> PopulatableToolRegistry:
        return InMemoryToolRegistry()


# --- construction -------------------------------------------------------


async def test_constructor_registers_in_order() -> None:
    """The convenience path is the registration path, not a second one."""
    registry = InMemoryToolRegistry([tool("smtp"), tool("cal", capability="create_event")])

    assert [each.id for each in await registry.all_tools()] == ["cal", "smtp"]


def test_constructor_refuses_two_definitions_sharing_an_id() -> None:
    """A composition root must not be able to smuggle in a conflict at build time."""
    with pytest.raises(ToolRegistrationError):
        InMemoryToolRegistry([tool(risk_level=RiskLevel.CRITICAL), tool(risk_level=RiskLevel.LOW)])


# --- ADR-0018 §5: the spent-id rule -------------------------------------


async def test_registering_an_identical_definition_is_idempotent() -> None:
    """So a composition root may run twice without special-casing."""
    registry = InMemoryToolRegistry([tool()])

    registry.register(tool())

    assert len(await registry.all_tools()) == 1


async def test_conflicting_redefinition_is_refused() -> None:
    """Metadata is a security control: CRITICAL must not become LOW in place."""
    registry = InMemoryToolRegistry([tool(risk_level=RiskLevel.CRITICAL)])

    with pytest.raises(ToolRegistrationError, match="smtp"):
        registry.register(tool(risk_level=RiskLevel.LOW))

    found = await registry.get("smtp")
    assert found is not None
    assert found.risk_level is RiskLevel.CRITICAL


async def test_a_deregistered_id_cannot_be_reused() -> None:
    """Deregistration is revocation, not renaming.

    A reusable id could be rebound between approval and execution: the user
    approves a REVERSIBLE send, an IRREVERSIBLE definition takes the name, and
    both the approval_ref and the bound_tool id still read as consistent.
    """
    registry = InMemoryToolRegistry([tool(reversibility=Reversibility.RECOVERABLE)])
    assert registry.deregister("smtp") is True

    with pytest.raises(ToolRegistrationError, match="deregistered"):
        registry.register(tool(reversibility=Reversibility.IRREVERSIBLE))

    assert await registry.get("smtp") is None


def test_an_identical_definition_cannot_resurrect_a_spent_id() -> None:
    """Sameness is not a licence to un-revoke.

    ADR-0016 permitted this: its §5 refused only a *different* definition,
    "whether or not the id was deregistered in between". ADR-0018 §5 reverses
    that, because otherwise revocation holds only until someone replays the
    original registration — which is exactly what a composition root re-running
    does.
    """
    registry = InMemoryToolRegistry([tool()])
    registry.deregister("smtp")

    with pytest.raises(ToolRegistrationError):
        registry.register(tool())


def test_deregistering_an_absent_tool_reports_false() -> None:
    registry = InMemoryToolRegistry([tool()])

    assert registry.deregister("nope") is False
    assert registry.deregister("smtp") is True
    assert registry.deregister("smtp") is False


async def test_a_deregistered_tool_leaves_the_capability_vocabulary() -> None:
    registry = InMemoryToolRegistry([tool()])

    registry.deregister("smtp")

    assert await registry.capabilities() == ()
    assert await registry.find("send_email") == []


# --- ADR-0018 §4: what is stored is valid and detached ------------------


async def test_a_definition_that_could_not_be_constructed_is_refused() -> None:
    """The ``__dict__`` bypass has to be closed on the way in, not only out.

    ``frozen=True`` does not stop ``object.__setattr__``, so a definition can
    reach ``register`` internally inconsistent — here the *inert email tool*,
    claiming no side effect while still disclosing personal data. Copying would
    store the contradiction as authoritative.
    """
    smuggled = tool()
    object.__setattr__(smuggled, "side_effecting", False)

    registry = InMemoryToolRegistry()

    with pytest.raises(ValidationError):
        registry.register(smuggled)

    assert await registry.get("smtp") is None


async def test_a_tampered_definition_is_refused_under_an_already_bound_id() -> None:
    """This is the §5 conflict rule, *not* §4's validity postcondition.

    The distinction matters enough that ADR-0018 records it: re-validation
    cannot catch this. A ``LOW`` risk level is perfectly valid, so rebuilding
    the tampered definition succeeds — what refuses it is that the id is already
    bound to a different definition. The next test pins what that leaves open.
    """
    registry = InMemoryToolRegistry([tool(risk_level=RiskLevel.CRITICAL)])

    tampered = tool(risk_level=RiskLevel.CRITICAL)
    object.__setattr__(tampered, "risk_level", RiskLevel.LOW)

    with pytest.raises(ToolRegistrationError):
        registry.register(tampered)

    stored = await registry.get("smtp")
    assert stored is not None
    assert stored.risk_level is RiskLevel.CRITICAL


async def test_a_tampered_definition_under_a_fresh_id_is_accepted() -> None:
    """A known, deliberate gap, pinned so nobody reads coverage into it.

    Validation answers "could this have been constructed?", never "is this what
    the author declared?", and the registry holds no trusted original to compare
    against. So a validly-tampered definition under an unused id is stored as
    given. Closing this needs a provenance boundary — a signature, a minting
    factory, or the pinned digest issue #54 proposes for the approval path —
    which no contract here provides (ADR-0018 §4).
    """
    tampered = tool("fresh", risk_level=RiskLevel.CRITICAL)
    object.__setattr__(tampered, "risk_level", RiskLevel.LOW)

    registry = InMemoryToolRegistry()
    registry.register(tampered)

    stored = await registry.get("fresh")
    assert stored is not None
    assert stored.risk_level is RiskLevel.LOW


async def test_mutating_the_definition_passed_in_does_not_reach_the_registry() -> None:
    """The detached half of §4's postcondition, on the way in."""
    original = tool(risk_level=RiskLevel.CRITICAL)
    registry = InMemoryToolRegistry([original])

    object.__setattr__(original, "risk_level", RiskLevel.LOW)

    stored = await registry.get("smtp")
    assert stored is not None
    assert stored.risk_level is RiskLevel.CRITICAL
