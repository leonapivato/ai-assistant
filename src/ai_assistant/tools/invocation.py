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

**There are two callable shapes, not one**, and the second is what that licence
was being kept for. :class:`ToolImplementation` takes the call's arguments;
:class:`EgressToolImplementation` takes them and the
:class:`~ai_assistant.core.types.EgressBinding` the authorising decision carries,
because a transport may re-derive none of what the ruling fixed (ADR-0148 §4).
:func:`_awaited` is where a registration's two halves are checked against each
other, and it refuses both mismatches before the deadline opens.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

import structlog
from pydantic import ValidationError

from ai_assistant.core.errors import ToolBindingError
from ai_assistant.core.types import (
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine, Mapping
    from datetime import timedelta

    from ai_assistant.core.types import EgressBinding, FrozenJson, ToolCall, ToolDefinition

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


@runtime_checkable
class EgressToolImplementation(Protocol):
    """The callable an **egress** integration binds to a declaration (ADR-0029 §1).

    :class:`ToolImplementation` with one addition it cannot do without: the
    :class:`~ai_assistant.core.types.EgressBinding` the authorising decision
    carries. A transport needs the account, the pinned endpoint and the canonical
    destination set the ruling fixed; it may re-derive none of them (ADR-0148 §4's
    third clause, which says a later lane "cannot satisfy it by re-deriving the set
    at the seam"); and the only holder of them at execution time is the request the
    executor read back out of the trail (ADR-0037 §3).

    **A second shape rather than a wider first one, for the reason ADR-0029 §1
    gives for splitting ``ToolInvoker`` off ``ToolRegistry``**: "the surface should
    not widen to cover a concern its consumers do not have." ``current_time`` and
    ``recall_memory`` have no business being handed a
    :class:`~ai_assistant.core.types.BoundAccount` carrying an account identity —
    Tier 1 personal data (ADR-0149 §3) — merely to satisfy a signature. Widening
    the one shape would hand every tool in the system that value forever, which is
    the direction ADR-0017 §8 wants to move away from and which ADR-0152 §10
    refuses one boundary out.

    **The method is named rather than being a second ``__call__``**, because
    ``runtime_checkable`` against a ``__call__``-only Protocol matches every
    callable in the language and so could not tell the two shapes apart at all. A
    distinct name makes the discrimination structural and total.

    Nothing else moves. ADR-0029 §6 still holds — no credential crosses this seam
    in either direction, and a binding carries none (ADR-0148 §6's exclusion
    clause). And choosing this shape is ADR-0029 §1's to give away: "How the
    callable is reached is `tools/`-internal, and this ADR does not contract it …
    What signature an integration author writes … is decided by the implementation
    PR — where it will have implementation contact — not blessed here."
    """

    async def invoke_bound(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
        egress_binding: EgressBinding,
    ) -> FrozenJson:
        """Perform the bound egress call and return its JSON-shaped output."""
        ...


#: Either callable shape a registration may bind. A union rather than a common
#: base class, because both are structural Protocols: an integration author
#: satisfies one by writing a method, never by inheriting anything.
BoundImplementation = ToolImplementation | EgressToolImplementation


def checked_pairing(implementation: BoundImplementation, call: ToolCall) -> None:
    """Refuse a callable whose shape and the call's egress binding disagree.

    **The check, separated from creating the coroutine, because ADR-0192 §1 puts
    the ledger claim between them.** "After ADR-0029 §2's three checks" is that
    section's floor and not the whole ordering: the claim is appended after
    *every* check that can raise a seam fault, and this pairing check is one of
    them — it reads the registry's callable and not the call alone, so those three
    do not subsume it. Claiming first would owe ADR-0192 §3 a completion carrying
    an outcome ADR-0029 computes for no ``ToolBindingError``: that error is given
    no ``ToolResult`` at all, only the executor's ``FAILED`` step. Performing the
    check without creating the coroutine is what lets the claim sit between the
    two without a never-awaited coroutine left behind on a refused claim.

    The cost is nothing — this enters no callable, performs no I/O and opens no
    deadline — and the gain is that a ``ToolBindingError`` stays exactly where
    ADR-0029 and ADR-0034 §1 already put it: a pre-callable exit with no claim
    appended and no row written.

    **Both mismatches are seam faults and both fail closed**, which is why they are
    checked here rather than left to whichever side would notice first:

    - an **egress** callable reached with no binding would be a tool that transmits
      being handed no account, no pinned endpoint and no authorised destination
      set. That is the state a binding seam answering "not an egress call" for a
      tool whose callable can only make one would produce — the mis-registration
      ADR-0152 §8 refuses, arriving one stage later.
    - an **ordinary** callable reached *with* a binding is the mirror image. A
      ruling was taken over a canonical destination set and a payload description,
      and the thing about to run can honour neither; ADR-0148 §4's third clause is
      that what is transmitted is bound to what was authorised, and a callable that
      never sees the binding is not held to it by anything.

    Neither is reachable through a correctly wired registry, and that is the
    argument *for* the check rather than against it: which callable a declaration
    binds is `tools/`-internal and contracted nowhere (ADR-0152 §10), so nothing
    else in the system would notice a root that paired them wrongly.

    Args:
        implementation: The registry's callable for the call's tool.
        call: The revalidated, detached call.

    Raises:
        ToolBindingError: If the callable's shape and the call's binding disagree.
    """
    binding = call.request.egress_binding
    if isinstance(implementation, EgressToolImplementation):
        if binding is None:
            msg = (
                f"tool {call.request.tool.id!r} is bound to an egress callable and this call "
                f"carries no egress binding, so there is no authorised account, endpoint or "
                f"destination set for it to transmit under (ADR-0148 §4, ADR-0152 §8)"
            )
            raise ToolBindingError(msg)
        return
    if binding is not None:
        msg = (
            f"tool {call.request.tool.id!r} was authorised as an egress call and is bound to a "
            f"callable that takes no egress binding, so what would run cannot be held to what "
            f"was authorised (ADR-0148 §4)"
        )
        raise ToolBindingError(msg)


def _awaited(
    implementation: BoundImplementation, call: ToolCall
) -> Coroutine[Any, Any, FrozenJson]:
    """Return the unawaited coroutine for ``call``, having checked the pairing.

    Created outside the deadline so that :func:`run_bound_call` starts the clock
    and the call together.

    Raises:
        ToolBindingError: If the callable's shape and the call's binding disagree
            (:func:`checked_pairing`). Re-checked here rather than assumed, so
            this function is safe to call on its own; the check is pure, so a
            caller that already ran it pays nothing.
    """
    checked_pairing(implementation, call)
    if isinstance(implementation, EgressToolImplementation):
        return implementation.invoke_bound(
            call.request.parameters,
            idempotency_key=call.idempotency_key,
            # `checked_pairing` refused this call unless the binding is present,
            # and it is a pure check with no suspension point, so nothing can have
            # removed it between there and here. A second `is None` branch would
            # be code no input reaches.
            egress_binding=cast("EgressBinding", call.request.egress_binding),
        )
    return implementation(call.request.parameters, idempotency_key=call.idempotency_key)


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
        outcome=definition.interrupted_outcome,
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
    implementation: BoundImplementation,
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
        implementation: The registry's callable for ``definition``, of either
            shape :data:`BoundImplementation` admits.
        definition: The registry's own declaration, used for classification.
        call: The revalidated, detached call.
        timeout: How long to wait; already checked by the caller.

    Returns:
        The classified outcome.

    Raises:
        ToolBindingError: If the callable's shape and the call's egress binding
            disagree (:func:`_awaited`). Raised **before** the deadline opens, so
            it is a seam fault like the three ``invoke`` performs and never a
            classified tool failure.
        CancelledError: If the invoking task was cancelled from outside.
    """
    # Created before the deadline opens, so a pairing fault is a raise out of the
    # seam rather than an `INTERNAL` result: nothing ran, and reporting that a tool
    # failed would be a falsehood about a call that was never made.
    running = _awaited(implementation, call)
    entered_with = _pending_cancellations()
    deadline = asyncio.timeout(timeout.total_seconds())
    try:
        async with deadline:
            output = await running
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


__all__ = [
    "BoundImplementation",
    "EgressToolImplementation",
    "ToolImplementation",
    "checked_pairing",
    "internal_failure",
    "run_bound_call",
]
