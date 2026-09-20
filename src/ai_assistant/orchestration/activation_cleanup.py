"""Await registered capture children through cancellation without orphaning them."""

from __future__ import annotations

import asyncio


async def drain_registered[T](task: asyncio.Task[T], *, cancel_on_interrupt: bool) -> T:
    """Wait for a tracked child to end before propagating this caller's cancellation.

    The engine registers the task before calling this helper. Ordinary recording
    may be cancelled by another interruption; deletion verification is shielded
    from that interruption. Both paths await actual termination, so a shutdown
    snapshot holding the parent cannot close stores underneath a later child.
    """
    interrupted: asyncio.CancelledError | None = None
    cancellation_sent = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            interrupted = exc
            if cancel_on_interrupt and not cancellation_sent and not task.done():
                task.cancel()
                cancellation_sent = True
        except Exception:
            # Read the terminal exception below even when caller cancellation
            # takes precedence, so no task failure is abandoned unobserved.
            break
    try:
        result = task.result()
    except BaseException:
        if interrupted is not None:
            raise interrupted from None
        raise
    if interrupted is not None:
        raise interrupted
    return result
