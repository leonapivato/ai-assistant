"""Pacing a hub stream onto a browser's, without cancelling its next step (ADR-0298 §7).

The gateway relays the hub's change stream to a browser change for change, and writes a
keep-alive of its own whenever a cadence passes with nothing to relay, so the page can
tell a quiet chat from a stream that has died (ADR-0175 §4's reason, one stream over).

**The hub's next step is awaited in a task of its own and never cancelled for a
keep-alive.** Bounding the wait on the iterator's ``__anext__`` with a timeout would
cancel that step each time the chat is quiet for a cadence — and cancelling a step of
the wire client's stream cancels the read under it, which closes the hub's stream and
loses whatever chunk was on its way. So the step is started once, waited on for at most
the cadence, and waited on again after the keep-alive; only closing the stream cancels
it. ``wire/server.py`` paces the hub's own heartbeat the same way (PR #2732).

**The step's task copies the context it is started in**, as every ``asyncio`` task
does, so a step started inside the browser's name (``acting_for``) carries it to every
frame the wire client writes for it, a reopened stream's among them.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from ai_assistant.core.streams import closing_stream

if TYPE_CHECKING:  # pragma: no cover — imported for typing alone
    from collections.abc import AsyncIterator


async def paced[T](items: AsyncIterator[T], *, every: float) -> AsyncIterator[T | None]:
    """Yield each item of ``items``, and ``None`` whenever ``every`` seconds pass without one.

    Ends when ``items`` does. Closing this iterator cancels the step in flight, if any,
    and closes ``items``.

    Args:
        items: The stream to relay. Closed on every exit.
        every: The cadence, in seconds: the longest this yields nothing for.

    Yields:
        The next item, or ``None`` for a cadence that passed without one.
    """
    async with closing_stream(items) as stream:
        step: asyncio.Future[T] | None = None
        try:
            while True:
                if step is None:
                    step = asyncio.ensure_future(anext(stream))
                done, _ = await asyncio.wait({step}, timeout=every)
                if not done:
                    yield None
                    continue
                taken, step = step, None
                try:
                    item = taken.result()
                except StopAsyncIteration:
                    return
                yield item
        finally:
            if step is not None:
                step.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await step


__all__ = ["paced"]
