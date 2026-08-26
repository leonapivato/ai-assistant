"""The spend admission at the invocation seam: a gate before the claim.

ADR-0194 §3, implemented once for `tools/`. :mod:`ai_assistant.tools.consume`
owns the two ledger appends that bracket the callable; this module owns the one
thing that happens **above** them — the gate is consulted, its reservation is
held for the length of the call, and its handle is released in a ``finally``
whatever the call did.

**Why it is its own module rather than three lines in the registry.** The
admission carries a deadline rule that is not the callable's: ADR-0194 §3 puts
the gate *inside* the window ADR-0029 §4 already enforces, so the two share one
budget and ``invoke`` expires at the caller's single original deadline rather
than at the sum of two. Keeping the arithmetic here is what lets that be read in
one place instead of reconstructed from a registry method that is mostly about
binding.

**Nothing here decides a spend.** The gate does, and the seam's whole obligation
is to consult it before the claim, hand it the pinned declaration, hold the
handle for exactly as long as the call runs, and let its refusal leave unchanged.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

from ai_assistant.tools.invocation import expiry_failure

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ai_assistant.core.protocols import SpendGate
    from ai_assistant.core.types import ToolCost, ToolDefinition, ToolResult


async def admitted_call(
    *,
    gate: SpendGate,
    estimate: ToolCost,
    definition: ToolDefinition,
    timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0029 §4, ADR-0194 §3)
    act: Callable[[timedelta], Awaitable[ToolResult]],
) -> ToolResult:
    """Admit this invocation, run ``act`` in what is left of ``timeout``, release.

    The admission is awaited **inside** the caller's deadline and the remainder of
    that same deadline is what ``act`` is given, so the two are one window
    (ADR-0194 §3). An implementation handing the admission its own fresh window
    and the callable another passes every never-answering-gate fixture and then
    returns successfully at nearly twice the deadline the caller set.

    A refusal leaves as the gate raised it. ADR-0194 §4 makes both spend classes
    payload-free where they are raised, and the seam between the gate and the
    caller is the one place that could undo it — so nothing here catches, wraps,
    re-raises an equivalent, or adds a note.

    Args:
        gate: The seam's :class:`~ai_assistant.core.protocols.SpendGate`, and
            never a ``SpendLedger``: an invoker able to read a totals projection
            has acquired a permissions-owned history it has no use for
            (ADR-0194 §5).
        estimate: The **pinned declaration** — the ``cost`` on the revalidated,
            detached copy ADR-0029 §2's checks produced, never read off the
            argument a caller passed (ADR-0194 §3, §11).
        definition: The registry's own declaration, whose ``interrupted_outcome``
            classifies a deadline that expires before the callable is reached.
        timeout: The caller's whole budget, already checked. The admission and the
            callable share it.
        act: Runs the claim, the callable and the completion, given what is left of
            the deadline. Called exactly once, and only after the gate admitted.

    Returns:
        Whatever ``act`` returned, or ADR-0029 §4's classification of an expiry
        that landed before ``act`` was ever entered.

    Raises:
        SpendCeilingError: If a configured ceiling would be crossed. The gate's own
            instance, unchanged.
        SpendUndeterminedError: If the spend could not be reduced to a number.
            Likewise.
        CancelledError: If the invoking task is cancelled from outside. ADR-0194 §3
            has the gate remove any reservation it had already recorded before the
            exception leaves it, so there is nothing here to release.
    """
    loop = asyncio.get_running_loop()
    expires_at = loop.time() + timeout.total_seconds()
    try:
        async with asyncio.timeout_at(expires_at):
            handle = await gate.admit_invocation(estimate=estimate)
    except TimeoutError:
        # **ADR-0029 §4's existing rule, unchanged and unnarrowed** (ADR-0194 §3).
        # `invoke` was entered and suspended in its own pre-call work, and nothing
        # states which await the expiry landed in — so this is the case ADR-0034 §1
        # keeps, not the pre-callable exit a *refusal* is. No claim was appended,
        # so there is no completion to owe and no handle to release.
        return expiry_failure(definition, timeout)
    try:
        remaining = expires_at - loop.time()
        if remaining <= 0:
            # The gate answered, but only as the window closed. Entering the
            # callable now would run it outside the deadline the caller set, and
            # `checked_timeout` refuses a non-positive duration for the reason this
            # branch exists: expiry is delivered at an await point, so a callable
            # performing a synchronous side effect before its first one would
            # already have acted.
            return expiry_failure(definition, timeout)
        return await act(timedelta(seconds=remaining))
    finally:
        # **Synchronous, so unwinding cannot lose it** (ADR-0194 §5): there is no
        # `await` here for a cancellation to be delivered at, and a release that
        # raised would replace the call's own outcome with a book-keeping failure —
        # which is why the contract forbids it raising at all rather than leaving
        # this frame to suppress one.
        gate.release_admission(handle)


__all__ = ["admitted_call"]
