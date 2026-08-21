"""Closing an async iterator a contract handed back (ADR-0060, ADR-0173 §5).

Two Protocols in :mod:`ai_assistant.core.protocols` now return an async iterator —
``StreamingCompleter.stream`` and ``AssistantEngine.converse_streaming`` — and both
place the same obligation on the caller in the same words: *stopping early is the
caller's to declare*. Python does not close an abandoned async iterator at the point
of abandonment, so a consumer that breaks out of its loop — a composing stage that
has run out of room, a hub whose peer sent a second request — leaves the resource
behind it open and still being paid for.

:func:`contextlib.aclosing` is exactly the right shape and its typeshed signature
will not take an ``AsyncIterator``: it is bound to a protocol declaring
``aclose()``, which ``AsyncIterator`` does not. The clause on both Protocols is that
what they return *does* support it, so this module states that in one place rather
than making every consumer restate it — which is the difference between one narrow
cast carrying a contract clause and three identical suppressions carrying nothing.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class _Closable(Protocol):
    """What both Protocols promise their iterator supports."""

    def aclose(self) -> Any:
        """Release whatever the iteration was holding."""
        ...


@asynccontextmanager
async def closing_stream[T](stream: AsyncIterator[T]) -> AsyncIterator[AsyncIterator[T]]:
    """Iterate ``stream`` and close it on every exit, early ones included.

    Args:
        stream: What a contract returning an async iterator handed back. Its own
            clause is what makes ``aclose()`` safe to require here.

    Yields:
        The same iterator, to be driven inside the block.
    """
    try:
        yield stream
    finally:
        await cast("_Closable", stream).aclose()
