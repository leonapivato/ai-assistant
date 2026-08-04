"""Context: assembles the situational context for a request.

Gathers the "right now" — time today, and (later) calendar, tasks, device — and
exposes it as a typed :class:`~ai_assistant.core.types.CurrentContext` for the
orchestration engine. Owns *what* the assistant is aware of at the moment of a
request; it is advisory, not durable state (ADR-0008).

The public contract is the ``ContextProvider`` Protocol in
`ai_assistant.core.protocols`. ``AssemblingContextProvider`` implements it by
composing internal ``ContextSource``s — ``ClockContextSource`` for the temporal
core, and ``CalendarContextSource`` for the first facet read from the world
(ADR-0096), which reads only under a live grant (ADR-0097 §5).
"""

from ai_assistant.context.provider import AssemblingContextProvider
from ai_assistant.context.sources import (
    CalendarContextSource,
    ClockContextSource,
    ContextSource,
)

__all__ = [
    "AssemblingContextProvider",
    "CalendarContextSource",
    "ClockContextSource",
    "ContextSource",
]
