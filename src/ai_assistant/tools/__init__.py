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

**This subsystem still transmits nothing.** ADR-0017 §2 leaves the egress seam
approved and *undesignated* until every §3 condition holds in code and a later
ADR ratifies that it does; ADR-0029 §7 inherits that list unabridged and
discharges none of it. An invocation contract reads like permission to call
things, and it is not.

That seam now exists by name — :mod:`ai_assistant.tools.egress` (ADR-0147 §3,
issue #66) — and holds nothing but a docstring. Naming it is what lets an
import-linter contract pin the boundary to one module rather than to this whole
package; naming is not designating, and none of ADR-0017 §3's fourteen
conditions is discharged by its existence.
"""

from __future__ import annotations

from ai_assistant.tools.builtin import (
    CURRENT_TIME,
    RECALL_MEMORY,
    CurrentTime,
    RecallMemory,
    build_default_registry,
)
from ai_assistant.tools.invocation import ToolImplementation
from ai_assistant.tools.registry import InMemoryToolRegistry

__all__ = [
    "CURRENT_TIME",
    "RECALL_MEMORY",
    "CurrentTime",
    "InMemoryToolRegistry",
    "RecallMemory",
    "ToolImplementation",
    "build_default_registry",
]
