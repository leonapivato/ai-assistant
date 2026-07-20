"""The canonical test double for the tool-registry contract (ADR-0016).

The shared fake for :class:`~ai_assistant.core.protocols.ToolRegistry`, so a
subsystem that selects or polices tools (`permissions`, `orchestration`, ...)
can test against a real, contract-correct registry *without importing the tools
subsystem's internals* (CLAUDE.md golden rule 1).

It deliberately re-implements the registration rules rather than importing
``ai_assistant.tools``: importing it would defeat the purpose, since a
consumer's tests would then pull in the very subsystem the fake stands in for.
The shared conformance suite is what keeps the two honest — both must pass it,
so a divergence is a test failure rather than a latent surprise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.core.errors import ToolRegistrationError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ai_assistant.core.types import ToolDefinition


class FakeToolRegistry:
    """A non-persistent ``ToolRegistry`` test double backed by dicts.

    Structurally implements :class:`~ai_assistant.core.protocols.ToolRegistry`
    — the four query methods — **and deliberately nothing more** (ADR-0018 §4
    and §5).

    It does not reproduce `tools/`'s registration lifecycle: no spent-id ledger,
    no re-validation on the way in. Those are internal to that subsystem, and
    this fake is importable by every other one, so mirroring them here would
    turn an internal lifecycle into an external compatibility contract — undoing
    the freedom ADR-0016 §5 bought by keeping the Protocol query-only. `tools/`
    must stay able to change how it registers without breaking a shared fake.

    :meth:`register` exists to *arrange* a registry, and enforces exactly one
    rule: no two definitions may share an id. That is the single arrangement
    mistake a consumer could plausibly make, and letting it pass silently would
    mean a test set up a registry the real one could never hold.

    Beyond the contract it records lookups in :attr:`lookups`, so a consumer's
    test can assert *that* selection consulted the registry and with what.
    """

    def __init__(self, tools: Iterable[ToolDefinition] = ()) -> None:
        """Create a registry holding ``tools``.

        Raises:
            ToolRegistrationError: If ``tools`` contains two definitions sharing
                an id.
        """
        self._tools: dict[str, ToolDefinition] = {}
        self.lookups: list[str] = []
        for tool in tools:
            self.register(tool)

    def register(self, tool: ToolDefinition) -> None:
        """Add ``tool`` so the query methods can find it.

        An arrangement helper, not a model of `tools/`'s registration rules; see
        the class docstring for why the difference is deliberate.

        Raises:
            ToolRegistrationError: If the id is already taken.
        """
        if tool.id in self._tools:
            msg = (
                f"tool id {tool.id!r} is already registered; a fixture holding two "
                "definitions under one id is a registry the real one could never hold"
            )
            raise ToolRegistrationError(msg)
        self._tools[tool.id] = tool.model_copy(deep=True)

    async def get(self, tool_id: str) -> ToolDefinition | None:
        """Return the definition registered as ``tool_id``, or ``None``."""
        self.lookups.append(tool_id)
        stored = self._tools.get(tool_id)
        return None if stored is None else stored.model_copy(deep=True)

    async def find(self, capability: str) -> list[ToolDefinition]:
        """Return every tool advertising ``capability``, ordered by id."""
        self.lookups.append(capability)
        matches = [tool for tool in self._tools.values() if tool.capability == capability]
        return [tool.model_copy(deep=True) for tool in sorted(matches, key=lambda t: t.id)]

    async def capabilities(self) -> tuple[str, ...]:
        """Return the advertised capability vocabulary, sorted and de-duplicated."""
        return tuple(sorted({tool.capability for tool in self._tools.values()}))

    async def all_tools(self) -> list[ToolDefinition]:
        """Return every live definition, ordered by id."""
        ordered = sorted(self._tools.values(), key=lambda tool: tool.id)
        return [tool.model_copy(deep=True) for tool in ordered]


__all__ = ["FakeToolRegistry"]
