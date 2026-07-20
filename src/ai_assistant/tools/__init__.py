"""Tools: the registry and integrations for external services.

Provides a uniform, discoverable interface over calendars, email, notes,
GitHub, smart-home devices, messaging, etc. Each integration is a self-contained
plugin registered here; the orchestration engine selects and invokes tools
without knowing their internals. Every tool invocation is subject to the
`permissions` layer.

Contract: :class:`~ai_assistant.core.protocols.ToolRegistry`, implemented by
:class:`~ai_assistant.tools.registry.InMemoryToolRegistry` (ADR-0016). The
contract is query-only — populating a registry is internal to this subsystem, so
binding a callable at registration, when invocation lands, is not a breaking
change. Invocation itself is deliberately not contracted yet.
"""

from __future__ import annotations

from ai_assistant.tools.registry import InMemoryToolRegistry

__all__ = ["InMemoryToolRegistry"]
