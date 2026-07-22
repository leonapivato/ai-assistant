"""Shared conformance suite for the ToolRegistry Protocol (ADR-0016).

Every ``ToolRegistry`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`ToolRegistryContract` and overrides the ``registry`` fixture.

`InMemoryToolRegistry` and `FakeToolRegistry` implement the registration rules
independently — the fake cannot import the subsystem it stands in for — so this
suite is what stops the two drifting.

**This suite covers the four query methods and nothing else** (ADR-0018 §3), and
that boundary is deliberate. `FakeToolRegistry` lives in `ai_assistant.testing`
and every subsystem can import it, so holding it to `tools/`'s registration
rules would make that subsystem's internal lifecycle an external compatibility
contract in practice — the freedom ADR-0016 §5 bought by keeping the Protocol
query-only, spent by accident.

Registration invariants (ADR-0018 §4 and §5 — the stored-state postcondition and
the spent-id rule) are therefore tested against `InMemoryToolRegistry` only, in
`tests/tools/test_registry.py`, beside the code they constrain.

The suite still calls ``register`` to *arrange* a populated registry. Using a
method for arrangement is not the same as contracting it: no assertion below
depends on what ``register`` does with a duplicate, a tampered, or a revoked id.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Protocol

import pytest

from ai_assistant.core.protocols import ToolRegistry
from ai_assistant.core.types import (
    CostBasis,
    DataTier,
    Idempotency,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.testing import FakeToolImplementation, succeeds


class PopulatableToolRegistry(ToolRegistry, Protocol):
    """A ``ToolRegistry`` plus the one method this suite needs to arrange one.

    An **arrangement** seam, not a contract: a suite must fill a registry before
    it can query one. Nothing here asserts how ``register`` behaves — that is
    `tools/`'s business (ADR-0018 §4 and §5) and is tested there.

    It takes the callable alongside the declaration because ADR-0029 §1 binds
    the two at registration, and a real registry has no way to hold one without
    the other. A query-only implementation ignores it.
    """

    def register(self, tool: ToolDefinition, implementation: FakeToolImplementation, /) -> None:
        """Add a tool, so the query tests have something to find."""
        ...


def given(registry: PopulatableToolRegistry, *tools: ToolDefinition) -> PopulatableToolRegistry:
    """Populate ``registry`` and hand it back, so arrange stays one statement.

    The subject fixture yields an *empty* registry rather than a factory that
    builds a populated one. That keeps the fixture producing the implementation
    itself, which is both what every other conformance suite here does and what
    the triad check inspects to prove the canonical fake is really bound.
    """
    for each in tools:
        registry.register(each, succeeds)
    return registry


def tool(tool_id: str = "smtp", **overrides: object) -> ToolDefinition:
    """Build a valid definition, overriding whichever field a test is about."""
    fields: dict[str, object] = {
        "id": tool_id,
        "capability": "send_email",
        "description": "Send an email.",
        "risk_level": RiskLevel.HIGH,
        "reversibility": Reversibility.IRREVERSIBLE,
        "side_effecting": True,
        "reads": (DataTier.PERSONAL,),
        "writes": (),
        "discloses": (DataTier.PERSONAL,),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NONE,
    }
    fields.update(overrides)
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


class ToolRegistryContract:
    """Behaviour every ``ToolRegistry`` implementation must exhibit."""

    @pytest.fixture
    def registry(self) -> PopulatableToolRegistry:
        """Return an empty registry under test."""
        raise NotImplementedError

    # --- lookup ---------------------------------------------------------

    async def test_registered_tool_is_retrievable(self, registry: PopulatableToolRegistry) -> None:
        given(registry, tool())

        found = await registry.get("smtp")

        assert found is not None
        assert found.capability == "send_email"

    async def test_unknown_id_reads_as_none(self, registry: PopulatableToolRegistry) -> None:
        given(registry, tool())

        assert await registry.get("nope") is None

    async def test_find_returns_every_candidate_for_a_capability(
        self, registry: PopulatableToolRegistry
    ) -> None:
        """Selection needs all candidates; the registry does not choose."""
        given(registry, tool("smtp"), tool("gmail"), tool("cal", capability="create_event"))

        found = await registry.find("send_email")

        assert [each.id for each in found] == ["gmail", "smtp"]

    async def test_unsatisfied_capability_is_empty_not_an_error(
        self, registry: PopulatableToolRegistry
    ) -> None:
        """A plan may name a capability nothing implements (SkipReason.NO_CAPABLE_TOOL)."""
        given(registry, tool())

        assert await registry.find("launch_rocket") == []

    async def test_find_and_all_tools_are_ordered_by_id(
        self, registry: PopulatableToolRegistry
    ) -> None:
        """Some total order must hold or implementations differ observably."""
        given(registry, tool("zulu"), tool("alpha"), tool("mike"))

        assert [each.id for each in await registry.find("send_email")] == ["alpha", "mike", "zulu"]
        assert [each.id for each in await registry.all_tools()] == ["alpha", "mike", "zulu"]

    async def test_capabilities_are_sorted_and_deduplicated(
        self, registry: PopulatableToolRegistry
    ) -> None:
        """The advertised vocabulary is normalised, not insertion-ordered."""
        given(
            registry,
            tool("zulu", capability="send_email"),
            tool("alpha", capability="create_event"),
            tool("mike", capability="send_email"),
        )

        assert await registry.capabilities() == ("create_event", "send_email")

    async def test_empty_registry_answers_emptily(self, registry: PopulatableToolRegistry) -> None:
        assert await registry.all_tools() == []
        assert await registry.capabilities() == ()
        assert await registry.get("smtp") is None

    # --- the registry owns what it holds --------------------------------

    @pytest.mark.parametrize("query", ["find", "all_tools"])
    async def test_a_returned_list_is_a_detached_snapshot(
        self, registry: PopulatableToolRegistry, query: str
    ) -> None:
        """A query must not hand back the registry's own collection.

        These methods return ``list`` to match ``MemoryStore.search`` and
        ``PlanStore.active_executions``, and a list is mutable — so an
        implementation returning its backing collection would let a caller's
        ``result.clear()`` deregister every tool through a *query*, routing
        around the registration lifecycle and the spent-id rule with it.
        """
        given(registry, tool("smtp"), tool("gmail"))

        async def fetch() -> list[ToolDefinition]:
            if query == "find":
                return await registry.find("send_email")
            return await registry.all_tools()

        (await fetch()).clear()

        assert [each.id for each in await fetch()] == ["gmail", "smtp"]

    @pytest.mark.parametrize("query", ["get", "find", "all_tools"])
    async def test_a_returned_definition_cannot_reach_registry_state(
        self, registry: PopulatableToolRegistry, query: str
    ) -> None:
        """Freezing stops attribute assignment, not ``__dict__`` writes.

        Every query, not just ``get``: an implementation could return a fresh
        list still holding its own definition objects, pass the detached-list
        test, and let a caller rewrite registered risk metadata through
        ``result[0]``.
        """
        given(registry, tool(risk_level=RiskLevel.CRITICAL))

        async def fetch() -> ToolDefinition:
            if query == "get":
                one = await registry.get("smtp")
                assert one is not None
                return one
            if query == "find":
                return (await registry.find("send_email"))[0]
            return (await registry.all_tools())[0]

        leaked = await fetch()
        object.__setattr__(leaked, "risk_level", RiskLevel.LOW)

        assert (await fetch()).risk_level is RiskLevel.CRITICAL

    @pytest.mark.parametrize("query", ["get", "find", "all_tools"])
    async def test_detachment_reaches_nested_values(
        self, registry: PopulatableToolRegistry, query: str
    ) -> None:
        """Detachment is recursive, not top-level (ADR-0018 §3).

        ``ToolDefinition`` holds a nested ``ToolCost``, so a *shallow* copy hands
        back a new definition sharing the stored cost — and
        ``result.cost.__dict__["amount"] = 0`` would then rewrite registry-owned
        security metadata through something technically detached, reintroducing
        underneath what the rule closed above.
        """
        given(
            registry,
            tool(cost=ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("5"), currency="USD")),
        )

        async def fetch() -> ToolDefinition:
            if query == "get":
                one = await registry.get("smtp")
                assert one is not None
                return one
            if query == "find":
                return (await registry.find("send_email"))[0]
            return (await registry.all_tools())[0]

        leaked = await fetch()
        object.__setattr__(leaked.cost, "amount", Decimal("0"))

        assert (await fetch()).cost.amount == Decimal("5")

    async def test_priced_and_keyed_metadata_round_trips(
        self, registry: PopulatableToolRegistry
    ) -> None:
        """The structured fields survive storage intact, not just the scalars."""
        given(
            registry,
            tool(
                cost=ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.002"), currency="USD"),
                idempotency=Idempotency.KEYED,
                idempotency_window=timedelta(hours=24),
                latency=timedelta(milliseconds=250),
            ),
        )

        found = await registry.get("smtp")

        assert found is not None
        assert found.cost.amount == Decimal("0.002")
        assert found.cost.currency == "USD"
        assert found.idempotency_window == timedelta(hours=24)
        assert found.latency == timedelta(milliseconds=250)
