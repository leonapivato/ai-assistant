"""The consume at the invocation seam: a claim before the act, a completion after.

ADR-0192 §1 and §3, implemented once for `tools/`. The registry owns the checks
and the binding; this module owns the two ledger appends that bracket the
callable, and every rule about what happens when one of them fails.

**Why it is its own module.** The two appends are not part of running a callable
— :mod:`ai_assistant.tools.invocation` classifies what came back and knows
nothing about an authorisation — and they carry the whole of ADR-0192 §1's and
§3's cancellation, absorption and commit-state reasoning. Keeping them together
is what lets that reasoning be read in one place rather than reconstructed from
two.

**The shape ADR-0192 §3 requires of each append is a retained, shielded await.**
A cancellation delivered into the ledger call itself is not enough: this
project's audit store absorbs such a cancellation, waits for its worker, and then
re-raises it *in place of* the value the worker produced (ADR-0054,
``permissions/audit.py``) — so a caller that let the cancellation reach that call
would lose the claim's own ``id`` for a claim that landed, and would then be
unable to complete it. So each append is held in a task nothing here cancels, the
cancellation is absorbed by this frame, the task's actual outcome is read, and
only then is the cancellation re-raised.

**Nothing outlives the frame.** Neither append is bounded by any deadline of this
seam's (ADR-0192 §1, §3), so the caller does not return until the retained task
has finished: no task is dropped, nothing is collected mid-write, and no
unretrieved exception is left behind. That is why this adds no shutdown member,
no drain hook and no lifecycle obligation to ``ToolInvoker``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from ai_assistant.core.errors import AssistantError, AuditError
from ai_assistant.core.types import CostBasis, ToolCost, fault_class_of

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

    from ai_assistant.core.protocols import InvocationLedger
    from ai_assistant.core.types import (
        PermissionDecision,
        ToolDefinition,
        ToolFailureKind,
        ToolInvocation,
        ToolOutcome,
        ToolResult,
    )

_log = structlog.get_logger(__name__)

#: The ledger operation a diagnostic names. Enumerated literals rather than a
#: method reference, because the diagnostic carries enumerated fields and no free
#: text (ADR-0192 §3).
CLAIM = "claim_invocation"
COMPLETION = "complete_invocation"

#: The event key every append failure is logged under.
APPEND_FAILED = "invocation_ledger_append_failed"


def unknown_cost() -> ToolCost:
    """What a completion records where nothing measured a figure (ADR-0192 §5).

    Minted per call rather than held as a module constant: ``frozen=True`` bounds
    the ordinary write path and not ``__dict__``, so a shared instance is a
    pointer through which one caller could rewrite the cost every later row
    carries.
    """
    return ToolCost(basis=CostBasis.UNKNOWN)


def pending_cancellations() -> int:
    """How many cancellation requests the invoking task is currently carrying.

    Read as a **baseline and a delta**, never as a boolean (ADR-0031 §2). The
    delta carries no provenance — ``cancelling()`` "is a count of requests, not a
    record of who made them" — so an **unmoved** count means no cancellation
    request reached this task during the call, and an **increased** count means
    one did, from a party the count cannot name.
    """
    task = asyncio.current_task()
    return 0 if task is None else task.cancelling()


async def _captured(coro: Coroutine[Any, Any, ToolInvocation]) -> ToolInvocation | BaseException:
    """Return what ``coro`` produced, or the exception it raised, as a value.

    See :func:`_driven` for why a failure leaves this task as a value: a
    ``BaseException`` propagating out of a task is re-raised into the event loop
    (ADR-0031 §4), and the frame that owes ADR-0192 §3's diagnostic would never
    resume to write it.
    """
    try:
        return await coro
    except BaseException as exc:
        # Every class, because the caller decides what each one means and this
        # frame decides nothing (ADR-0192 §1, §3).
        return exc


async def _driven(
    coro: Coroutine[Any, Any, ToolInvocation],
) -> tuple[ToolInvocation | BaseException, bool]:
    """Drive one ledger append to its outcome, absorbing every cancellation.

    The loop is what makes the absorption robust rather than single-shot: a
    caller that shields the first await and then awaits the retained task bare
    loses the append's real outcome to the second cancellation. Nothing here
    cancels the task, and nothing calls ``uncancel()`` — the count is the
    discriminator every caller below reads, so lowering it would erase the one
    fact this frame has about who was cancelled.

    **The append's failure is carried out as a value rather than raised by the
    task**, and that is not tidiness. ADR-0031 §4 measured the mechanism:
    ``Task.__step`` sets a ``KeyboardInterrupt`` on the future **and** re-raises
    it into the event loop, which is the loop coming down — so a
    ``BaseException`` left to propagate out of a retained task takes the loop with
    it before this frame can emit the diagnostic ADR-0192 §3 requires of *every*
    audit-write failure, "wherever it arose, the retained appends included".
    Capturing it keeps the loop alive, lets the diagnostic be written, and lets
    the caller re-raise it **unchanged** from its own frame, which is ADR-0029
    §3's rule kept rather than worked around. What ADR-0192 §3 declines to state
    is the *outward class* at ``invoke``'s boundary, and nothing here asserts one.

    Args:
        coro: The unawaited ledger call.

    Returns:
        The stored row or the failure the append raised, and **whether a
        cancellation was delivered into this frame while it was in flight**.

        That second fact is reported rather than inferred from
        ``Task.cancelling()``, and the two are not the same question. The count's
        *delta* tells a collaborator's invented ``CancelledError`` from an external
        one (ADR-0031 §2) — a classification of something the ledger **returned**.
        A cancellation the event loop **delivered here** is external whatever the
        delta says: a caller already carrying a request when ``invoke`` was entered
        moves the count by nothing, and ADR-0192 §1 still requires that "a
        cancellation delivered while the append is in flight is absorbed, the
        task's result is observed, and the cancellation is **then re-raised**".
        Reading the delta alone would swallow it, which is the one thing ADR-0060
        §1 says a method never does.
    """
    absorbed = False
    task = asyncio.ensure_future(_captured(coro))
    while not task.done():
        try:
            # `wait` never raises the task's own exception and never cancels the
            # futures it waits on, so the task survives a cancellation delivered
            # here and its outcome is still readable below.
            await asyncio.wait({task})
        except asyncio.CancelledError:
            absorbed = True
            continue
    if task.cancelled():
        msg = "the ledger append cancelled its own task"
        return asyncio.CancelledError(msg), absorbed
    return task.result(), absorbed


def _diagnose(
    operation: str, error: BaseException, outcome: ToolOutcome | None = None
) -> BaseException | None:
    """Report an append failure to the operator, in enumerated fields only.

    **Three fields exhaust it** (ADR-0192 §3): the ledger operation, always; the
    exception's fault class, where the exception is an ``Exception``; and the
    outcome that was being written, where the operation is a completion. No
    exception instance, no message, no ``str()`` of one and no member of a cause
    chain — not the ledger's own, and not one an injected callable raised.

    The class is :func:`~ai_assistant.core.types.fault_class_of` and never a raw
    ``type(error).__name__``: a class **name** is as attacker-controlled as a
    message, and an injected clock or store can raise
    ``type("recipient@example.com", (RuntimeError,), {})()``. It carries **no
    identifier** either — not the claim's, not the decision's, not the step's —
    because ``DurableIdentifier`` is a non-blank string a caller minted and
    ADR-0031 §5 records that such a value is not contractually log-safe.

    **This never raises, and that is load-bearing rather than defensive.**
    ``fault_class_of`` guards its ``__name__`` read against ``Exception`` and
    deliberately not ``BaseException``, "so a ``CancelledError`` raised *by the
    name read* is delivered onward as ADR-0060 §1 requires" — so a hostile
    metaclass can raise one out of the classifier. Letting it leave *this* frame
    would carry it past the disposition below and decide the call's exit: on the
    claim path a failure whose count was unmoved would leave as a
    ``CancelledError`` instead of the ``AuditError`` ADR-0192 §1 requires, so the
    executor would record a call that provably never ran as interrupted; on the
    completion path it would discard a ``ToolResult`` the tool had already
    produced, which §3 calls the one outcome worse than an incomplete record. So
    the field is **omitted** — which is §3's own shape for an exception no class
    can be read from, not a literal invented for the position — and the
    classifier's own failure is handed back to the path's rules.

    Returns:
        The ``BaseException`` the class read raised, where one did, for the caller
        to attach as context. ``None`` otherwise.
    """
    fields: dict[str, object] = {"operation": operation}
    unclassifiable: BaseException | None = None
    if isinstance(error, Exception):
        try:
            fields["fault_class"] = fault_class_of(error)
        except BaseException as exc:
            unclassifiable = exc
    if outcome is not None:
        fields["outcome"] = outcome
    _log.warning(APPEND_FAILED, **fields)
    return unclassifiable


def _chained(error: BaseException, unclassifiable: BaseException | None) -> None:
    """Keep a diagnostic's own failure on the record without letting it decide the exit.

    :func:`_diagnose` hands back the ``BaseException`` its class read raised, where
    one did. It is attached to the append's failure as that exception's context, so
    it survives on the chain a caller can walk — and it changes nothing about which
    branch below is taken, which is the whole point of returning it rather than
    raising it.
    """
    if unclassifiable is not None and error.__context__ is None:
        error.__context__ = unclassifiable


@dataclass(frozen=True, slots=True)
class _Completion:
    """The three fields a completion row carries beyond its claim (ADR-0192 §2).

    Gathered into one value because they are one decision — what ADR-0029 §§3-4
    computed for this exit — and because each caller below derives all three
    together, from a ``ToolResult`` or from a cancellation.
    """

    #: What ADR-0029 §§3-4 computed for the exit.
    outcome: ToolOutcome
    #: The figure the tool reported, or an ``UNKNOWN`` basis where it reported
    #: none. Never ``ToolDefinition.cost`` (ADR-0192 §5).
    incurred_cost: ToolCost
    #: Transcribed from the result that carried one, never synthesised. A
    #: completion derived from no result carries none (ADR-0192 §2).
    failure_kind: ToolFailureKind | None = None


@dataclass(frozen=True, slots=True)
class _Appended:
    """What a completion append left behind for its caller to act on."""

    #: The append's failure, where one must accompany a propagating
    #: cancellation. ``None`` where the append succeeded or where its failure was
    #: absorbed (ADR-0192 §3).
    failure: BaseException | None
    #: Whether a cancellation request reached this task while the append was in
    #: flight.
    cancelled: bool


async def _complete(
    ledger: InvocationLedger,
    claim: ToolInvocation,
    completion: _Completion,
    *,
    propagating: bool,
) -> _Appended:
    """Append the completion of ``claim``, and decide what its failure means.

    **The obligation is to make the call**, and a completion that is refused or
    fails to write changes nothing about the call itself (ADR-0192 §3): the
    caller returns the ``ToolResult`` the act produced, or re-raises what it was
    already raising. A ``SUCCEEDED`` side effect is not reported as failed
    because a disk was full.

    The absorbing rule is decided **by class, not by origin**: every ``Exception``
    raised on this path is a completion failure — the ledger's own refusals, the
    ``AuditError`` it translated, and an exception the clock callable raised on
    its own account and the ledger propagated unwrapped (ADR-0026 §2). Its one
    companion rule is the cancellation, which turns on the ``Task.cancelling()``
    count and not on its class or its origin.

    Args:
        ledger: The invoker's ledger.
        claim: The row :meth:`InvocationLedger.claim_invocation` returned.
        completion: The three fields the row carries beyond its claim.
        propagating: Whether an external cancellation is already leaving the
            seam. Where it is, ADR-0060 §1's precedence governs and no failure of
            this append is absorbed — it becomes the cancellation's cause.

    Returns:
        The failure to attach to a propagating cancellation, and whether one was
        delivered while this append was in flight.

    Raises:
        BaseException: A non-cancellation ``BaseException`` raised on this path
            while no external cancellation is propagating is not absorbed
            (ADR-0192 §3): a process being torn down is not a refusal, and
            converting a ``KeyboardInterrupt`` into a returned result is the
            conversion ADR-0029 §3 forbids.
    """
    entered_with = pending_cancellations()
    appended, absorbed = await _driven(
        ledger.complete_invocation(
            claim_id=claim.id,
            outcome=completion.outcome,
            incurred_cost=completion.incurred_cost,
            failure_kind=completion.failure_kind,
        )
    )
    cancelled = absorbed or pending_cancellations() > entered_with
    if not isinstance(appended, BaseException):
        return _Appended(None, cancelled)
    error = appended

    _chained(error, _diagnose(COMPLETION, error, completion.outcome))
    if propagating or cancelled:
        return _Appended(error, cancelled)
    if isinstance(error, asyncio.CancelledError | Exception):
        # A collaborator's invented cancellation, with nothing cancelled, is not a
        # cancellation of this call and is absorbed exactly as any other
        # completion failure is (ADR-0192 §3, ADR-0029 §4, ADR-0031 §2).
        return _Appended(None, False)
    raise error


def _cancellation(reason: str, cause: BaseException | None) -> asyncio.CancelledError:
    """Build the ``CancelledError`` this seam delivers onward, carrying ``cause``.

    Freshly raised rather than re-raised where the original was consumed inside a
    retained append. What matters is that the cancellation reaches the executor
    rather than being answered with a result (ADR-0060 §1).
    """
    cancellation = asyncio.CancelledError(reason)
    if cause is not None:
        cancellation.__cause__ = cause
    return cancellation


async def _claimed(
    ledger: InvocationLedger, *, definition: ToolDefinition, decision: PermissionDecision
) -> ToolInvocation:
    """Append the claim, or leave by the exit ADR-0192 §1 gives its failure.

    **Every ``AssistantError`` this append raises is an exit before the callable
    is entered**, so each qualifies on ADR-0034 §1's *second* ground — "the
    contract says the exit precedes the callable" — and the executor commits
    ``RUNNING → FAILED`` on the window rather than on a list of causes. The one
    branch where an ``AssistantError`` is not what leaves is an external
    cancellation pending: there the ``CancelledError`` leaves carrying the
    append's failure as its cause, and ADR-0029 §4's classification governs.

    **What the store already committed, stands.** Where this append raises, no
    claim was *observed* — and that is all that may be said. The write may have
    committed before the failure reached the frame (ADR-0060 §1), ADR-0192 §6
    offers no selective delete, and nothing here writes a compensating delete, a
    tombstone or a marker to tell the two apart.

    Raises:
        CancelledError: If a cancellation request reached this task while the
            append was in flight. It is delivered onward whatever the append did.
        AuthorisationSpentError: If the consume refused this claim.
        UnrecordedAuthorisationError: If the trail holds no decision equal to
            ``decision`` under its id, or holds one whose ruling is not ``ALLOW``.
        AuditError: If the append failed with anything that is not an
            ``AssistantError`` — including a ``CancelledError`` a collaborator
            raised with nothing cancelled, which is not a cancellation of this
            call and does not leave as one (ADR-0192 §1).
    """
    entered_with = pending_cancellations()
    appended, absorbed = await _driven(ledger.claim_invocation(decision=decision))
    cancelled = absorbed or pending_cancellations() > entered_with

    if not isinstance(appended, BaseException):
        claim = appended
        if not cancelled:
            return claim
        # The claim landed and the call is cancelled before the callable is
        # entered: the completion carrying what ADR-0029 §4 computes for that
        # cancellation is owed, and then the cancellation is re-raised (§1).
        completed = await _complete(
            ledger,
            claim,
            _Completion(outcome=definition.interrupted_outcome, incurred_cost=unknown_cost()),
            propagating=True,
        )
        raise _cancellation(
            "the invoking task was cancelled while the invocation's claim was in flight",
            completed.failure,
        )

    error = appended
    _chained(error, _diagnose(CLAIM, error))
    if cancelled:
        raise _cancellation(
            "the invoking task was cancelled while the invocation's claim was in flight", error
        )
    if isinstance(error, asyncio.CancelledError):
        msg = (
            "the invocation ledger raised a cancellation with nothing cancelled, "
            "so the claim was not appended"
        )
        raise AuditError(msg) from error
    if isinstance(error, AssistantError):
        raise error
    if isinstance(error, Exception):
        msg = "the invocation ledger could not append the claim"
        raise AuditError(msg) from error
    raise error


async def consumed_call(
    *,
    ledger: InvocationLedger,
    definition: ToolDefinition,
    decision: PermissionDecision,
    act: Callable[[], Awaitable[ToolResult]],
) -> ToolResult:
    """Claim ``decision``, run ``act``, and complete the claim on every exit.

    The claim is appended **immediately before the callable is entered**, after
    every check that can raise a seam fault (ADR-0192 §1) — which is what keeps
    two records from disagreeing: before the claim, ADR-0034 §1's window and no
    invocation row; after it, an act that may have run and a row that says so.

    Once a claim is appended, a completion is attempted on **every** exit this
    frame observes — a returned ``ToolResult``, an expired deadline, a
    cancellation — carrying the outcome ADR-0029 §§3-4 already compute for that
    exit. No seam fault is among them, because §1 places every check that raises
    one before the claim. A **`BaseException` that is not a cancellation** is not
    an exit that clause reaches: ADR-0029 §3 requires it to propagate unchanged,
    no outcome is invented for it, no completion is written, and the claim is
    left open — the honest state for a process being torn down.

    Args:
        ledger: The invoker's ledger, and never an ``AuditTrail`` (ADR-0192 §2).
        definition: The **registry's** own declaration, whose
            ``interrupted_outcome`` classifies a cancellation.
        decision: The authority for the act, passed by value because the ledger
            requires it to equal the decision the store holds under that id.
        act: Runs the bound callable under this seam's deadline and classifies
            what came back. Called exactly once, and only after the claim landed.

    Returns:
        Whatever ``act`` returned, unaltered. A completion that failed does not
        change it.
    """
    claim = await _claimed(ledger, definition=definition, decision=decision)
    try:
        result = await act()
    except asyncio.CancelledError as cancellation:
        appended = await _complete(
            ledger,
            claim,
            _Completion(outcome=definition.interrupted_outcome, incurred_cost=unknown_cost()),
            propagating=True,
        )
        if appended.failure is None:
            raise
        # The caught cancellation is re-raised **as itself**, never rendered and
        # never replaced. ``Task.cancel`` accepts an arbitrary message object, so
        # ``str(cancellation)`` runs a ``__str__`` this seam does not own — one
        # that can raise, and would then reach the caller in place of the
        # externally delivered cancellation, which is the conversion ADR-0060 §1
        # and ADR-0192 §3 both refuse. Attaching the cause preserves the append's
        # failure without touching the exception's identity.
        cancellation.__cause__ = appended.failure
        raise

    appended = await _complete(
        ledger,
        claim,
        _Completion(
            outcome=result.outcome,
            # A ``ToolResult`` carrying a figure maps unaltered; one carrying none
            # maps to an ``UNKNOWN`` basis. ``ToolDefinition.cost`` appears on no
            # row of the trail, on this path or any other (ADR-0192 §5).
            incurred_cost=(
                result.incurred_cost if result.incurred_cost is not None else unknown_cost()
            ),
            # Transcribed, never synthesised: a completion derived from no result
            # carries none (ADR-0192 §2).
            failure_kind=None if result.failure is None else result.failure.kind,
        ),
        propagating=False,
    )
    if appended.cancelled:
        raise _cancellation(
            "the invoking task was cancelled while the invocation's completion was in flight",
            appended.failure,
        )
    return result


__all__ = ["APPEND_FAILED", "CLAIM", "COMPLETION", "consumed_call", "unknown_cost"]
