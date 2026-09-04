"""Tools: the registry, the invocation seam, and integrations for external services.

Provides a uniform, discoverable interface over calendars, email, notes,
GitHub, smart-home devices, messaging, etc. Each integration is a self-contained
plugin registered here; the orchestration engine selects and invokes tools
without knowing their internals. Every tool invocation is subject to the
`permissions` layer.

Contracts: :class:`~ai_assistant.core.protocols.ToolRegistry` (ADR-0016) and
:class:`~ai_assistant.core.protocols.ToolInvoker` (ADR-0029), both implemented
by :class:`~ai_assistant.tools.registry.InMemoryToolRegistry` — one object over
one binding, which is how ADR-0029 §1's "invocable if and only if registered"
stays true. Registration itself is on neither contract: what an integration
author writes is this subsystem's own business, in the way `context` keeps its
``ContextSource`` seam behind ``ContextProvider`` (ADR-0008).

**This subsystem transmits, from one module and under one designation.**
ADR-0154 §1 designates :mod:`ai_assistant.tools.egress` and §4 attests every one
of ADR-0017 §3's fourteen conditions in code; ADR-0155 answers #95, which is what
ADR-0154 §6's third clause made blocking for any registration at the seam. That
module is the only one under this package that may open a network connection —
the boundary an import-linter contract pins to one module rather than to this
whole package (ADR-0147 §3, issue #66) — and
:func:`~ai_assistant.tools.builtin.build_send_email_integration` is the only place
in production that constructs a transport from it.

**A registration is still a deployment fact rather than a package fact.** One tool
per connected account (ADR-0148 §6), so ``send_email`` reaches the registry only
where a deployment has named the account it sends as and the endpoint it submits
to; where it has not, this subsystem holds only the one local, read-only tool
``current_time`` (ADR-0208 §1).
"""

from __future__ import annotations

from ai_assistant.tools.builtin import (
    CURRENT_TIME,
    CurrentTime,
    EgressIntegration,
    WebSearchIntegration,
    build_default_registry,
    build_send_email_integration,
    build_web_search_integration,
    egress_registrations,
)
from ai_assistant.tools.invocation import EgressToolImplementation, ToolImplementation
from ai_assistant.tools.registry import InMemoryToolRegistry

__all__ = [
    "CURRENT_TIME",
    "CurrentTime",
    "EgressIntegration",
    "EgressToolImplementation",
    "InMemoryToolRegistry",
    "ToolImplementation",
    "WebSearchIntegration",
    "build_default_registry",
    "build_send_email_integration",
    "build_web_search_integration",
    "egress_registrations",
]
