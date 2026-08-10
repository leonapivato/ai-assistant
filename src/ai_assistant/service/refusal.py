"""One exception type for everything ADR-0123 tells the backup tools to refuse.

The decision is written almost entirely as refusals — a contended lock, a sidecar
beside a database, an entry that is not a regular file, a destination that
already exists, a destination inside the source, a target that is the live data
directory, an artifact from a newer format, a member the manifest does not list.
Each is a condition a human must change before the same command could succeed,
which is exactly ADR-0083 §5's test for a stay-down exit: "would restarting,
unchanged, ever succeed?"

**So they share a type rather than a code path.** The entry points catch this one
class, print its message, and return :data:`~ai_assistant.service.exits.EXIT_DEPLOYMENT`
— the same vocabulary the hub and the other three offline tools use, so an
operator reads one set of meanings across all five. Everything that is *not* a
refusal keeps going to :func:`~ai_assistant.service.exits.classify`, which is
where an unexpected fault belongs and where §5's "a spurious restart is
recoverable and a spurious ``78`` is an outage" default lives.

It lives in its own module because both entry points and both format modules
raise it, and the format modules are imported by the entry points rather than the
other way round — anywhere else and the import graph would have a cycle in it.
"""

from __future__ import annotations

from ai_assistant.core.errors import AssistantError


class RefusalError(AssistantError):
    """A condition ADR-0123 requires the tool to refuse rather than work around.

    The message is the whole diagnostic: it names the thing refused and, where
    the ADR asks for one, the remedy. It is printed to an operator, so it is
    written for one.
    """
