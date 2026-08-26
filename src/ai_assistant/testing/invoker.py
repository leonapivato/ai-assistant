"""The canonical test double for the tool-invocation contract (ADR-0029).

The shared fake for :class:`~ai_assistant.core.protocols.ToolInvoker`, so a
subsystem that executes a plan step (`orchestration`, above all) can test
against a real, contract-correct seam *without importing the tools subsystem's
internals* (CLAUDE.md golden rule 1).

Like :class:`~ai_assistant.testing.tools.FakeToolRegistry` it deliberately
re-implements the rules rather than importing ``ai_assistant.tools``: importing
it would defeat the purpose, since a consumer's tests would then pull in the
very subsystem the fake stands in for. The shared conformance suite is what
keeps the two honest — both must pass it, so a divergence is a test failure
rather than a latent surprise.

It presents **both** faces of the registry over one binding, because ADR-0029
§1's biconditional is stated about an implementation and the suite checks it:
``all_tools()`` and the set of ids ``invoke`` acts on are read from the same
dict.

Since ADR-0192 it also reproduces the **consume**: a claim appended immediately
before the callable and a completion on every exit past it, each driven as a
retained, shielded await. That is duplicated here rather than imported for the
reason everything else in this module is — the fake may not import the subsystem
it stands in for — and the shared conformance suite is what holds the two to the
same observable behaviour.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Protocol

import structlog
from pydantic import ValidationError

from ai_assistant.core.errors import (
    AssistantError,
    AuditError,
    ToolBindingError,
    ToolRegistrationError,
)
from ai_assistant.core.types import (
    CostBasis,
    ToolCall,
    ToolCost,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
    fault_class_of,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine, Iterable, Mapping

    from ai_assistant.core.protocols import InvocationLedger
    from ai_assistant.core.types import (
        FrozenJson,
        PermissionDecision,
        ToolDefinition,
        ToolInvocation,
    )


class FakeToolImplementation(Protocol):
    """The callable a fake binding runs.

    Mirrors what `tools/` binds, without importing it: ADR-0029 §1 leaves the
    callable's shape internal to that subsystem, so this is a parallel
    declaration rather than a shared contract, and the conformance suite is what
    holds the two to the same observable behaviour.
    """

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
    ) -> FrozenJson:
        """Perform the call and return its JSON-shaped output."""
        ...


async def succeeds(
    parameters: Mapping[str, FrozenJson],  # noqa: ARG001 — a stand-in ignores its arguments
    *,
    idempotency_key: str | None,  # noqa: ARG001
) -> FrozenJson:
    """A tool that does nothing and succeeds — the default arrangement."""
    return None


def _checked_timeout(timeout: object) -> timedelta:
    """Reject a deadline ``invoke`` could not enforce (ADR-0029 §4).

    The annotation is not the enforcement — Python does not check one at runtime
    and this argument crosses a Protocol boundary — so the guard is total over
    the value. A zero or negative duration is refused rather than treated as an
    instantly-expired deadline, because expiry is delivered at an await point
    and a callable acting before its first ``await`` would already have acted.

    Raises:
        ValueError: If ``timeout`` is not a strictly positive ``timedelta``.
    """
    if not isinstance(timeout, timedelta):
        msg = f"timeout must be a timedelta, got {type(timeout).__name__}"
        raise ValueError(msg)
    if timeout <= timedelta(0):
        msg = f"timeout must be strictly positive, got {timeout}"
        raise ValueError(msg)
    return timeout


@dataclass(frozen=True, slots=True)
class _Binding:
    """One id's declaration and the callable that satisfies it."""

    definition: ToolDefinition
    implementation: FakeToolImplementation


class FakeToolInvoker:
    """A non-persistent ``ToolInvoker`` (and ``ToolRegistry``) test double.

    Arrange it with :meth:`register`, which takes a declaration and the callable
    that satisfies it — a pair, because ADR-0029 §1's biconditional has no room
    for a declared-but-unrunnable id.

    It does **not** reproduce `tools/`'s registration lifecycle: no spent-id
    ledger, no re-validation on the way in. Those are internal to that
    subsystem, and this fake is importable by every other one, so mirroring them
    here would turn an internal lifecycle into an external compatibility
    contract — the same boundary ``FakeToolRegistry`` draws. What it *does*
    reproduce is everything ADR-0029 makes observable through ``invoke``: the
    three ordered checks, the deadline, and the classification.

    Beyond the contract it records every call it accepted in :attr:`invocations`,
    so a consumer's test can assert that execution reached the seam and with
    what.
    """

    def __init__(
        self,
        tools: Iterable[tuple[ToolDefinition, FakeToolImplementation]] = (),
        *,
        ledger: InvocationLedger | None = None,
    ) -> None:
        """Create an invoker holding ``tools``.

        Args:
            tools: ``(definition, callable)`` pairs to register immediately.
            ledger: The ``InvocationLedger`` :meth:`invoke` claims and completes
                through (ADR-0192 §1, §3), and **never** an ``AuditTrail``.

                **Keyword-only and defaulted, for the reason
                ``InMemoryToolRegistry``'s is**: the composition root always
                supplies one in production, and what the default buys is an
                arrangement for a consumer's test about something else — an
                executor fixture driving the deadline or the classification has no
                authorisation recorded anywhere and no consume to observe. An
                invoker holding none appends nothing and refuses nothing on the
                ground that an authorisation is spent.

        Raises:
            ToolRegistrationError: If ``tools`` contains two definitions sharing
                an id.
        """
        self._bindings: dict[str, _Binding] = {}
        self._ledger = ledger
        self.invocations: list[ToolCall] = []
        for tool, implementation in tools:
            self.register(tool, implementation)

    def register(
        self, tool: ToolDefinition, implementation: FakeToolImplementation = succeeds, /
    ) -> None:
        """Bind ``tool`` and the callable that satisfies it.

        An arrangement helper, not a model of `tools/`'s registration rules; see
        the class docstring for why the difference is deliberate. The callable
        defaults to one that succeeds with no output, so a test about binding or
        authorisation need not supply one.

        Raises:
            ToolRegistrationError: If the id is already taken.
        """
        if tool.id in self._bindings:
            msg = (
                f"tool id {tool.id!r} is already registered; a fixture holding two "
                "definitions under one id is a registry the real one could never hold"
            )
            raise ToolRegistrationError(msg)
        self._bindings[tool.id] = _Binding(tool.model_copy(deep=True), implementation)

    # --- the ToolRegistry face -------------------------------------------

    def _definitions(self) -> list[ToolDefinition]:
        """Return every declaration, ordered by id, still attached."""
        return sorted(
            (binding.definition for binding in self._bindings.values()), key=lambda tool: tool.id
        )

    async def get(self, tool_id: str) -> ToolDefinition | None:
        """Return the definition registered as ``tool_id``, or ``None``."""
        stored = self._bindings.get(tool_id)
        return None if stored is None else stored.definition.model_copy(deep=True)

    async def find(self, capability: str) -> list[ToolDefinition]:
        """Return every tool advertising ``capability``, ordered by id."""
        return [
            tool.model_copy(deep=True)
            for tool in self._definitions()
            if tool.capability == capability
        ]

    async def capabilities(self) -> tuple[str, ...]:
        """Return the advertised capability vocabulary, sorted and de-duplicated."""
        return tuple(sorted({binding.definition.capability for binding in self._bindings.values()}))

    async def all_tools(self) -> list[ToolDefinition]:
        """Return every definition, ordered by id."""
        return [tool.model_copy(deep=True) for tool in self._definitions()]

    # --- the ToolInvoker face --------------------------------------------

    async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0029 §4); wrapping it outside would cancel the invoker mid-await
        """Run ``call`` against this fake's own binding for it.

        See :meth:`~ai_assistant.core.protocols.ToolInvoker.invoke` for the
        contract; every rule it states is reproduced here.

        Where this fake holds a ledger, the claim is appended after those three
        checks and immediately before the callable, and a completion follows on
        every exit past it (ADR-0192 §1, §3). This fake binds one callable shape,
        so it has no callable-shape pairing check to place — that check is
        `tools/`-internal (ADR-0152 §10) and its ordering against the claim is
        pinned where it lives.

        Raises:
            ValueError: If ``timeout`` is not a strictly positive ``timedelta``.
            ToolBindingError: If the call does not survive revalidation, names
                an unbound id, carries a definition unequal to this fake's own,
                or is not authorised by its decision. **No claim is appended for
                any of them.**
            AuthorisationSpentError: If the ledger refuses the claim because the
                authorisation is spent (ADR-0192 §1).
            UnrecordedAuthorisationError: If the trail holds no decision equal to
                this call's under its id, or holds one that is not an ``ALLOW``.
            AuditError: If the claim append failed with anything that is not an
                ``AssistantError``. A failure of the **completion** append is
                absorbed instead and reaches the operator as a diagnostic.
            CancelledError: If the invoking task is cancelled from outside.
        """
        _checked_timeout(timeout)

        try:
            checked = ToolCall.model_validate(call.model_dump())
        except ValidationError as exc:
            msg = "the call did not survive revalidation, so it is not the call that was authorised"
            raise ToolBindingError(msg) from exc

        binding = self._bindings.get(checked.request.tool.id)
        if binding is None:
            msg = f"tool id {checked.request.tool.id!r} is not bound, so there is nothing to invoke"
            raise ToolBindingError(msg)
        if binding.definition != checked.request.tool:
            msg = (
                f"the definition carried by the call for {checked.request.tool.id!r} is not the "
                "one this invoker holds, so the thing about to run is not the thing declared"
            )
            raise ToolBindingError(msg)
        if not checked.decision.authorises(checked.request):
            msg = (
                f"decision {checked.decision.id!r} does not authorise this request, "
                "so the thing about to run is not the thing that was authorised"
            )
            raise ToolBindingError(msg)

        self.invocations.append(checked)

        async def act() -> ToolResult:
            return await self._run(binding, checked, timeout)

        if self._ledger is None:
            return await act()
        return await _consumed_call(
            ledger=self._ledger,
            definition=binding.definition,
            decision=checked.decision,
            act=act,
        )

    async def _run(self, binding: _Binding, call: ToolCall, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0029 §4); wrapping it outside would cancel the invoker mid-await
        """Await the callable under the deadline and classify what came back.

        The interruption state is read from the task and the deadline on *every*
        exit, the normal return included: a callable that catches its
        cancellation and returns a value would otherwise be reported
        ``SUCCEEDED`` after a cancelled turn, or after outrunning its deadline.
        """
        entered_with = _pending_cancellations()
        deadline = asyncio.timeout(timeout.total_seconds())
        try:
            async with deadline:
                output = await binding.implementation(
                    call.request.parameters, idempotency_key=call.idempotency_key
                )
        except asyncio.CancelledError as exc:
            if _pending_cancellations() > entered_with:
                raise
            return _internal(binding.definition, exc)
        except Exception as exc:
            return _interruption(binding.definition, timeout, deadline, entered_with) or _internal(
                binding.definition, exc
            )

        interrupted = _interruption(binding.definition, timeout, deadline, entered_with)
        if interrupted is not None:
            return interrupted

        try:
            return ToolResult(outcome=ToolOutcome.SUCCEEDED, output=output)
        except ValidationError as exc:
            return _internal(binding.definition, exc)


def _pending_cancellations() -> int:
    """How many cancellation requests the invoking task is currently carrying.

    Read as a baseline and a delta, never as a boolean: ``Task.cancelling()`` is
    a lifetime count that only ``uncancel()`` lowers, so a caller that absorbed
    an earlier cancellation still reports a positive one with nothing about
    *this* call cancelled.
    """
    task = asyncio.current_task()
    return 0 if task is None else task.cancelling()


def _interruption(
    definition: ToolDefinition,
    timeout: timedelta,
    deadline: asyncio.Timeout,
    cancellations_on_entry: int,
) -> ToolResult | None:
    """Report what an interruption the tool *absorbed* means, if there was one.

    A pending external cancellation is re-raised rather than reported — ADR-0029
    §4 keeps the commit-then-re-raise on the executor — while an expired
    deadline is reported, because that is the seam's own knowledge and the only
    form in which ``INDETERMINATE`` can be delivered.

    Raises:
        CancelledError: If a cancellation of the invoking task is still pending.
    """
    if _pending_cancellations() > cancellations_on_entry:
        msg = f"tool {definition.id!r} absorbed the cancellation of its invoking task"
        raise asyncio.CancelledError(msg)
    if deadline.expired():
        return _expired(definition, timeout)
    return None


def _expired(definition: ToolDefinition, timeout: timedelta) -> ToolResult:
    """Describe this seam's own deadline expiring."""
    return ToolResult(
        outcome=definition.interrupted_outcome,
        failure=ToolFailure(
            kind=ToolFailureKind.TIMED_OUT,
            message=f"tool {definition.id!r} did not finish within {timeout}",
        ),
    )


def _internal(definition: ToolDefinition, exc: BaseException) -> ToolResult:
    """Describe a broken tool without quoting it — never ``str(exc)`` (ADR-0029 §3)."""
    return ToolResult(
        outcome=ToolOutcome.FAILED,
        failure=ToolFailure(
            kind=ToolFailureKind.INTERNAL,
            message=f"{type(exc).__name__} escaped tool {definition.id!r}",
        ),
    )


# --- the consume (ADR-0192 §1, §3) ------------------------------------------
#
# A parallel implementation of `ai_assistant.tools.consume`, written here for the
# reason the rest of this module is: the fake may not import the subsystem it
# stands in for. The shared conformance suite drives both, so a divergence is a
# test failure rather than a latent surprise.

_log = structlog.get_logger(__name__)

#: The ledger operation a diagnostic names (ADR-0192 §3).
CLAIM = "claim_invocation"
COMPLETION = "complete_invocation"

#: The event key every append failure is logged under.
APPEND_FAILED = "invocation_ledger_append_failed"


def _unknown_cost() -> ToolCost:
    """What a completion records where nothing measured a figure (ADR-0192 §5).

    Minted per call rather than held as a module constant: ``frozen=True`` bounds
    the ordinary write path and not ``__dict__``, so a shared instance is a
    pointer through which one caller could rewrite the cost every later row
    carries.
    """
    return ToolCost(basis=CostBasis.UNKNOWN)


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


async def _driven(coro: Coroutine[Any, Any, ToolInvocation]) -> ToolInvocation | BaseException:
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
        The stored row, or the failure the append raised.
    """
    task = asyncio.ensure_future(_captured(coro))
    while not task.done():
        try:
            # `wait` never raises the task's own exception and never cancels the
            # futures it waits on, so the task survives a cancellation delivered
            # here and its outcome is still readable below.
            await asyncio.wait({task})
        except asyncio.CancelledError:
            continue
    if task.cancelled():
        msg = "the ledger append cancelled its own task"
        return asyncio.CancelledError(msg)
    return task.result()


def _diagnose(operation: str, error: BaseException, outcome: ToolOutcome | None = None) -> None:
    """Report an append failure in enumerated fields only (ADR-0192 §3).

    Three fields exhaust it: the operation, always; the fault class, where the
    exception is an ``Exception``; and the outcome, where the operation is a
    completion. No instance, no message, no cause chain and no identifier.
    """
    fields: dict[str, object] = {"operation": operation}
    if isinstance(error, Exception):
        fields["fault_class"] = fault_class_of(error)
    if outcome is not None:
        fields["outcome"] = outcome
    _log.warning(APPEND_FAILED, **fields)


@dataclass(frozen=True, slots=True)
class _Completion:
    """The three fields a completion row carries beyond its claim (ADR-0192 §2)."""

    outcome: ToolOutcome
    incurred_cost: ToolCost
    failure_kind: ToolFailureKind | None = None


@dataclass(frozen=True, slots=True)
class _Appended:
    """What a completion append left behind for its caller to act on."""

    failure: BaseException | None
    cancelled: bool


async def _complete(
    ledger: InvocationLedger,
    claim: ToolInvocation,
    completion: _Completion,
    *,
    propagating: bool,
) -> _Appended:
    """Append the completion of ``claim``, and decide what its failure means.

    The obligation is to make the call; a completion that is refused or fails to
    write changes nothing about the call itself (ADR-0192 §3). Absorption is
    decided **by class, not by origin**, with one companion rule: a
    ``CancelledError`` turns on the ``Task.cancelling()`` count instead.

    Raises:
        BaseException: A non-cancellation ``BaseException`` raised here while no
            external cancellation is propagating is not absorbed.
    """
    entered_with = _pending_cancellations()
    appended = await _driven(
        ledger.complete_invocation(
            claim_id=claim.id,
            outcome=completion.outcome,
            incurred_cost=completion.incurred_cost,
            failure_kind=completion.failure_kind,
        )
    )
    cancelled = _pending_cancellations() > entered_with
    if not isinstance(appended, BaseException):
        return _Appended(None, cancelled)
    error = appended

    _diagnose(COMPLETION, error, completion.outcome)
    if propagating or cancelled:
        return _Appended(error, cancelled)
    if isinstance(error, asyncio.CancelledError | Exception):
        return _Appended(None, False)
    raise error


def _cancellation(reason: str, cause: BaseException | None) -> asyncio.CancelledError:
    """Build the ``CancelledError`` this seam delivers onward, carrying ``cause``."""
    cancellation = asyncio.CancelledError(reason)
    if cause is not None:
        cancellation.__cause__ = cause
    return cancellation


async def _claimed(
    ledger: InvocationLedger, *, definition: ToolDefinition, decision: PermissionDecision
) -> ToolInvocation:
    """Append the claim, or leave by the exit ADR-0192 §1 gives its failure.

    Every ``AssistantError`` this append raises is an exit before the callable is
    entered, qualifying on ADR-0034 §1's second ground. The one branch where an
    ``AssistantError`` is not what leaves is an external cancellation pending:
    there the ``CancelledError`` leaves carrying the append's failure as its cause.

    Where this append raises, no claim was *observed* — and that is all that may
    be said. The write may have committed before the failure reached the frame
    (ADR-0060 §1), and nothing here writes a compensating delete or a marker.
    """
    entered_with = _pending_cancellations()
    appended = await _driven(ledger.claim_invocation(decision=decision))
    cancelled = _pending_cancellations() > entered_with

    if not isinstance(appended, BaseException):
        claim = appended
        if not cancelled:
            return claim
        completed = await _complete(
            ledger,
            claim,
            _Completion(outcome=definition.interrupted_outcome, incurred_cost=_unknown_cost()),
            propagating=True,
        )
        raise _cancellation(
            "the invoking task was cancelled while the invocation's claim was in flight",
            completed.failure,
        )

    error = appended
    _diagnose(CLAIM, error)
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


async def _consumed_call(
    *,
    ledger: InvocationLedger,
    definition: ToolDefinition,
    decision: PermissionDecision,
    act: Callable[[], Awaitable[ToolResult]],
) -> ToolResult:
    """Claim ``decision``, run ``act``, and complete the claim on every exit.

    A ``BaseException`` that is not a cancellation is not an exit the completion
    clause reaches: it propagates unchanged, no outcome is invented, no completion
    is written, and the claim is left open (ADR-0029 §3, ADR-0192 §3).
    """
    claim = await _claimed(ledger, definition=definition, decision=decision)
    try:
        result = await act()
    except asyncio.CancelledError as cancellation:
        appended = await _complete(
            ledger,
            claim,
            _Completion(outcome=definition.interrupted_outcome, incurred_cost=_unknown_cost()),
            propagating=True,
        )
        if appended.failure is None:
            raise
        raise _cancellation(str(cancellation), appended.failure) from appended.failure

    appended = await _complete(
        ledger,
        claim,
        _Completion(
            outcome=result.outcome,
            incurred_cost=(
                result.incurred_cost if result.incurred_cost is not None else _unknown_cost()
            ),
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


__all__ = [
    "APPEND_FAILED",
    "CLAIM",
    "COMPLETION",
    "FakeToolImplementation",
    "FakeToolInvoker",
    "succeeds",
]
