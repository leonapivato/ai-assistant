"""Running one bound callable under a deadline, and classifying what came back.

The half of ADR-0029 §3 and §4 that is about *execution* rather than about binding.
:mod:`ai_assistant.tools.registry` owns the binding and the three checks that
precede a call; everything here starts once a trusted ``(definition, callable)``
pair is in hand.

The callable's own signature is deliberately **not** a ``core`` contract.
ADR-0029 §1 leaves "how the callable is reached" internal to `tools/`, on
ADR-0008's precedent — a ``ContextProvider`` crosses the boundary while the
``ContextSource`` seam that populates it stays inside `context/`. Registration
is this subsystem's ``ContextSource``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol

import structlog
from pydantic import ValidationError

from ai_assistant.core.types import (
    Idempotency,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import timedelta

    from ai_assistant.core.types import FrozenJson, ToolCall, ToolDefinition

_log = structlog.get_logger(__name__)


class ToolImplementation(Protocol):
    """The callable an integration binds to a declaration at registration.

    Receives the call's arguments and, for a ``KEYED`` tool, the derived
    idempotency key as an **opaque string** (ADR-0029 §5). A tool whose upstream
    constrains the key's format maps it inside the integration, and that mapping
    must be deterministic: one that is not a function of the key reintroduces
    the variance the derivation removed.

    It receives no credential, and returns none. A tool that needs one obtains
    it itself; nothing about a secret crosses the invocation seam in either
    direction (ADR-0029 §6).

    An implementation **raises** to report a failure it cannot classify; the
    seam turns that into an ``INTERNAL`` result. One that can classify its own
    failure returns nothing useful by raising — it should be given the vocabulary
    of :class:`~ai_assistant.core.types.ToolFailureKind` by a future integration
    ADR, which this one does not decide.
    """

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
    ) -> FrozenJson:
        """Perform the call and return its JSON-shaped output."""
        ...


def interrupted_outcome(definition: ToolDefinition) -> ToolOutcome:
    """Classify a call cut short by a deadline or a cancellation (ADR-0029 §4).

    > On timeout or cancellation, the outcome is ``FAILED`` when the tool is not
    > ``side_effecting``, **or** its ``idempotency`` is ``NATURAL``. Otherwise it
    > is ``INDETERMINATE``.

    A read that timed out changed nothing, and a ``NATURAL`` tool is idempotent
    by nature (ADR-0016 §4), so whether it acted does not change what a repeat
    does. Everything else is exactly ADR-0014 §4's case — "a crash between a
    tool's side effect and the commit … cannot be distinguished from a crash
    *before* the effect" — reached through a deadline rather than through a
    crash, and it gets the same answer, because guessing in either direction is
    what that ADR refused.

    Args:
        definition: The **registry's** declaration for the bound tool, never
            ``call.request.tool``. The seam's checks all ran before the callable
            started, so a declaration mutated afterwards is re-examined by
            nothing: a side-effecting, non-``NATURAL`` call whose definition were
            flipped to read-only mid-flight would be classified ``FAILED``, which
            is a possible side effect recorded as certainly-nothing-happened.
    """
    if not definition.side_effecting or definition.idempotency is Idempotency.NATURAL:
        return ToolOutcome.FAILED
    return ToolOutcome.INDETERMINATE


def internal_failure(definition: ToolDefinition, exc: BaseException) -> ToolResult:
    """Describe a broken tool without quoting it (ADR-0029 §3).

    **The message names the exception's type and the tool's id, and nothing
    else.** It does not interpolate ``str(exc)``, which is where a
    ``RuntimeError`` quoting a recipient would arrive — and ``core/logging.py``
    names that exact shape, ``error=str(exc)``, as the Tier 1 leak its key-based
    redactor cannot see. The cost is a thinner diagnostic for a broken
    integration, accepted because the alternative is a disclosure on the failure
    path of every tool nobody thought about.
    """
    _log.warning(
        "tool_implementation_raised",
        tool_id=definition.id,
        # The type, never the instance: rendering the exception is the leak.
        error_type=type(exc).__name__,
    )
    return ToolResult(
        outcome=ToolOutcome.FAILED,
        failure=ToolFailure(
            kind=ToolFailureKind.INTERNAL,
            message=f"{type(exc).__name__} escaped tool {definition.id!r}",
        ),
    )


def _expiry_failure(definition: ToolDefinition, timeout: timedelta) -> ToolResult:
    """Describe this seam's own deadline expiring."""
    return ToolResult(
        outcome=interrupted_outcome(definition),
        failure=ToolFailure(
            kind=ToolFailureKind.TIMED_OUT,
            message=f"tool {definition.id!r} did not finish within {timeout}",
        ),
    )


def _pending_cancellations() -> int:
    """How many cancellation requests the invoking task is currently carrying.

    Read as a **baseline and a delta**, never as a boolean. ``Task.cancelling()``
    is a lifetime count that only ``uncancel()`` lowers, so a caller that
    absorbed an earlier cancellation to finish some work and then invoked a tool
    still reports a positive count with nothing about *this* call cancelled.
    Treating that as provenance would fail every subsequent invocation on that
    task as cancelled — and would convert a tool's invented ``CancelledError``,
    which ADR-0029 §4 requires to be ``INTERNAL``, into a cancellation on the
    strength of something that happened before the seam was entered.
    """
    task = asyncio.current_task()
    return 0 if task is None else task.cancelling()


def _interruption(
    definition: ToolDefinition,
    timeout: timedelta,
    deadline: asyncio.Timeout,
    cancellations_on_entry: int,
) -> ToolResult | None:
    """Answer what an interruption the tool *absorbed* means, if there was one.

    Nothing forces a callable to let a cancellation through: one that catches
    ``CancelledError`` and returns a value leaves the seam holding an output and
    no exception. Trusting that return would be the seam's worst available bug —
    a cancelled turn reported as ``SUCCEEDED``, or a call that outran the
    deadline reported as though it had met it. So the state is read from the
    task and the timeout rather than inferred from what came back.

    A pending external cancellation is re-raised rather than reported, because
    ADR-0029 §4 keeps that on the executor: swallowing it would break structured
    concurrency and shutdown. An expired deadline is reported, because that is
    the seam's own knowledge and the only form in which ``INDETERMINATE`` can be
    delivered at all.

    **What this does not close, stated rather than papered over.** The deadline
    half is tool-proof — ``Timeout.expired()`` is the seam's own state and no
    callable can reset it. The cancellation half is not: a callable that catches
    an *external* cancellation and then calls ``uncancel()`` on the invoking task
    restores the count to its baseline, and the call comes back as an ordinary
    result. That is the same family ADR-0029 §4 already calls unclosable from
    this side — "a tool that suppresses its own cancellation can outlive its
    deadline, and no seam can prevent that" — and the mitigation it names, one
    stalled turn on a loop that keeps running, applies unchanged. Closing it
    would mean running the callable in a child task, which is the shape §10
    warns against ("an implementation quietly acquiring a watchdog") and would
    make ``invoke``'s cooperative limit a different, weaker thing. Tracked as an
    issue rather than fixed here, because the fix is a contract question.

    Returns:
        The expiry result if this deadline expired, or ``None`` if the call was
        not interrupted.

    Raises:
        CancelledError: If a cancellation of the invoking task is still pending.
    """
    if _pending_cancellations() > cancellations_on_entry:
        # Freshly raised rather than re-raised: the original was consumed inside
        # the callable. What matters is that the cancellation reaches the
        # executor rather than being answered with a result.
        msg = f"tool {definition.id!r} absorbed the cancellation of its invoking task"
        raise asyncio.CancelledError(msg)
    if deadline.expired():
        return _expiry_failure(definition, timeout)
    return None


async def run_bound_call(
    implementation: ToolImplementation,
    *,
    definition: ToolDefinition,
    call: ToolCall,
    timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0029 §4)
) -> ToolResult:
    """Await ``implementation`` under this seam's deadline and classify the result.

    Every classification here keys on something the seam itself established,
    never on an exception's type alone:

    - ``TIMED_OUT`` requires **this** deadline to have expired. An upstream SDK
      raising Python's ``TimeoutError`` for its own reasons, well inside our
      budget, is an exception like any other and becomes ``INTERNAL`` — because
      labelling it ``TIMED_OUT`` would, for a side-effecting tool, escalate a
      call that failed fast and provably did nothing into one whose effect is
      unknown, and therefore out of retry.
    - A ``CancelledError`` is a cancellation only if one was actually
      **requested** — of this deadline, or of the invoking task. If none was,
      the tool invented it, and a tool that raised is ``INTERNAL``. Otherwise it
      propagates: swallowing it would break structured concurrency and shutdown,
      and there is no return path from a task being torn down.
    - **Neither of those is inferred from what the callable did**, because a
      callable that catches a cancellation and returns a value leaves the seam
      holding an output and no exception at all. So the deadline and the task
      are read directly, on the normal-return path as well as the raising one —
      see :func:`_interruption`. Without that, a cancelled turn comes back
      ``SUCCEEDED``, and a side-effecting call that outran its deadline comes
      back as though it had met it.

    ``BaseException`` otherwise propagates unchanged, which is the boundary
    ADR-0026 §2 drew for ``checked_clock``: a guard whose own failure modes
    bypass the failure path it specifies is enforcing nothing.

    Args:
        implementation: The registry's callable for ``definition``.
        definition: The registry's own declaration, used for classification.
        call: The revalidated, detached call.
        timeout: How long to wait; already checked by the caller.

    Returns:
        The classified outcome.

    Raises:
        CancelledError: If the invoking task was cancelled from outside.
    """
    entered_with = _pending_cancellations()
    deadline = asyncio.timeout(timeout.total_seconds())
    try:
        async with deadline:
            output = await implementation(
                call.request.parameters, idempotency_key=call.idempotency_key
            )
    except asyncio.CancelledError as exc:
        if _pending_cancellations() > entered_with:
            raise
        return internal_failure(definition, exc)
    except Exception as exc:
        # Python's own `TimeoutError` arrives here too, and is *not* special:
        # what makes an expiry an expiry is this deadline having fired, which
        # only `_interruption` can say.
        return _interruption(definition, timeout, deadline, entered_with) or internal_failure(
            definition, exc
        )

    interrupted = _interruption(definition, timeout, deadline, entered_with)
    if interrupted is not None:
        return interrupted

    try:
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, output=output)
    except ValidationError as exc:
        # The tool returned something `FrozenJsonValue` refuses — a set, a NaN.
        # The tool is broken, and saying so is more useful than storing
        # something unserialisable (ADR-0029 §3).
        return internal_failure(definition, exc)


__all__ = ["ToolImplementation", "internal_failure", "interrupted_outcome", "run_bound_call"]
