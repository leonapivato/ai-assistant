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
import contextlib
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final, Protocol, cast

import structlog
from pydantic import ValidationError

from ai_assistant.core.errors import (
    AssistantError,
    AuditError,
    ToolBindingError,
    ToolRegistrationError,
)
from ai_assistant.core.types import (
    UNREPRESENTABLE_FAULT_CLASS,
    CostBasis,
    ToolCall,
    ToolCost,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
    fault_class_of,
)
from ai_assistant.testing.permissions import FakeAuditTrail

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine, Iterable, Mapping
    from types import GetSetDescriptorType

    from ai_assistant.core.protocols import InvocationLedger, SpendGate
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

    **A plain ``timedelta`` is returned, rebuilt from the base class's own
    descriptors and never the caller's object**, for the reason
    `ai_assistant.tools.registry` states at length: ``isinstance`` admits a
    subclass, and the duration is read after the claim has landed, where an
    overridden ``total_seconds`` raising would leave a claim open with no
    completion and returning ``inf`` would disable the deadline.

    Returns:
        A plain ``timedelta`` of exactly the same duration.

    Raises:
        ValueError: If ``timeout`` is not a strictly positive ``timedelta``.
    """
    if not isinstance(timeout, timedelta):
        msg = f"timeout must be a timedelta, got {type(timeout).__name__}"
        raise ValueError(msg)
    duration = timedelta(
        days=timedelta.days.__get__(timeout),
        seconds=timedelta.seconds.__get__(timeout),
        microseconds=timedelta.microseconds.__get__(timeout),
    )
    if duration <= timedelta(0):
        msg = f"timeout must be strictly positive, got {duration}"
        raise ValueError(msg)
    return duration


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
        ledger: InvocationLedger,
        gate: SpendGate,
    ) -> None:
        """Create an invoker holding ``tools``.

        Args:
            tools: ``(definition, callable)`` pairs to register immediately.
            ledger: The ``InvocationLedger`` :meth:`invoke` claims and completes
                through (ADR-0192 §1, §3), and **never** an ``AuditTrail``.

                **Keyword-only and required, for the reason
                ``InMemoryToolRegistry``'s is**: ADR-0192 §9 requires the canonical
                fake to reproduce the consume, and a fake that could be built
                without a ledger would let a consumer's test pass behaviour
                production rejects — the same call twice under one spendable
                ``ALLOW``. :func:`ai_assistant.testing.invoker_over` builds the
                pair a consumer's fixture wants.
            gate: The ``SpendGate`` every invocation is admitted by, before the
                claim (ADR-0194 §3), and **never** a ``SpendLedger``.

                **Keyword-only and required**, for ``ledger``'s reason: ADR-0194
                §11 requires the canonical fake to reproduce the admission, and a
                fake that could be built without a gate would let a consumer's test
                pass behaviour production rejects — a call reaching the world with
                no ceiling consulted. ``FakeAuditTrail`` is a ``SpendGate`` and,
                built with no ceiling, admits everything unconditionally, which is
                what :func:`invoker_over` hands over.

        Raises:
            ToolRegistrationError: If ``tools`` contains two definitions sharing
                an id.
        """
        self._bindings: dict[str, _Binding] = {}
        self._ledger = ledger
        self._gate = gate
        self.invocations: list[ToolCall] = []
        for tool, implementation in tools:
            self.register(tool, implementation)

    @property
    def ledger(self) -> InvocationLedger:
        """The ``InvocationLedger`` this seam claims and completes through.

        Read-only, and public because two callers legitimately need to *see* which
        object was wired: ADR-0192 §9's composition test, which asserts the invoker
        was handed the ledger face of the one audit store and not a second one over
        the same file, and a conformance subclass arranging the authorisations its
        calls carry. Neither can be written against a private attribute without the
        access itself becoming the thing under test.

        It hands out the collaborator, never a wider face: what a holder gets is
        exactly what this seam was given, which can neither record a
        ``PermissionDecision``, nor read one, nor export, nor ``clear``
        (ADR-0192 §2).
        """
        return self._ledger

    @property
    def gate(self) -> SpendGate:
        """The ``SpendGate`` this seam admits through.

        Read-only, and public for the reason :attr:`ledger` is: ADR-0194 §5 makes
        the composition root the sole wirer, and its test asserts the invoker was
        handed the gate face of the one store rather than a second holder over the
        same rows — which cannot be written against a private attribute without the
        access itself becoming the thing under test.
        """
        return self._gate

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

        The claim is appended after those three checks and immediately before the
        callable, and a completion follows on every exit past it (ADR-0192 §1, §3).
        This fake binds one callable shape, so it has no callable-shape pairing
        check to place — that check is `tools/`-internal (ADR-0152 §10) and its
        ordering against the claim is pinned where it lives.

        **The spend admission sits between them** (ADR-0194 §3): the gate is
        consulted after the three checks and before the claim, is handed the
        ``ToolCost`` on the revalidated copy, shares the caller's one deadline with
        the callable, and its handle is released in a ``finally`` on every path. A
        refused call reaches no callable, appends no claim and appends no
        completion, and the gate's own exception is what leaves — unwrapped and
        unannotated, so ADR-0194 §4's payload-free rule survives this seam.

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
            SpendCeilingError: If the gate refuses because a configured ceiling
                would be crossed (ADR-0194 §4). The gate's own instance, unchanged.
            SpendUndeterminedError: If the gate refuses because the spend could not
                be reduced to a number. Likewise.
            CancelledError: If the invoking task is cancelled from outside.
        """
        duration = _checked_timeout(timeout)

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

        async def act(remaining: timedelta) -> ToolResult:
            # Recorded **after** the claim is accepted and immediately before the
            # callable, because this list is what a consumer's test reads to prove
            # that nothing was accepted when a call was refused (ADR-0192 §1,
            # ADR-0194 §3). A call the ledger or the gate refused reached no
            # callable, so it belongs here as little as one the three checks
            # refused.
            self.invocations.append(checked)
            # `remaining`, not the caller's object — see `_checked_timeout`. It is
            # what is left of `duration` after the admission, because ADR-0194 §3
            # makes the two one window.
            return await self._run(binding, checked, remaining, stated=duration)

        async def consume(remaining: timedelta) -> ToolResult:
            return await _consumed_call(
                ledger=self._ledger,
                definition=binding.definition,
                decision=checked.decision,
                act=lambda: act(remaining),
            )

        # **The gate, and then the claim** (ADR-0194 §3, ADR-0192 §1). The estimate
        # is read off the revalidated, detached copy and never off the argument.
        return await _admitted_call(
            gate=self._gate,
            estimate=checked.request.tool.cost,
            definition=binding.definition,
            timeout=duration,
            act=consume,
        )

    async def _run(
        self,
        binding: _Binding,
        call: ToolCall,
        timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0029 §4); wrapping it outside would cancel the invoker mid-await
        *,
        stated: timedelta | None = None,
    ) -> ToolResult:
        """Await the callable under the deadline and classify what came back.

        The interruption state is read from the task and the deadline on *every*
        exit, the normal return included: a callable that catches its
        cancellation and returns a value would otherwise be reported
        ``SUCCEEDED`` after a cancelled turn, or after outrunning its deadline.

        ``timeout`` is what is **left** of the caller's budget after the admission
        (ADR-0194 §3); ``stated`` is the whole of it, and names the figure an expiry
        message carries so a user reads the deadline they set.
        """
        entered_with = _pending_cancellations()
        named = timeout if stated is None else stated
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
            return _interruption(binding.definition, named, deadline, entered_with) or _internal(
                binding.definition, exc
            )

        interrupted = _interruption(binding.definition, named, deadline, entered_with)
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


_INVENTED_CANCELLATION = "CancelledError"


def _fault_class(exc: BaseException) -> str:
    """Name the exception's class, totally, and with nothing the tool controls.

    See `ai_assistant.tools.invocation` for the whole of it. Read after the claim,
    so an unguarded read would leave the frame in place of the ``ToolResult``;
    classified by ``core``'s own ``fault_class_of``, so an attacker-controlled
    name cannot reach a message or a log; a ``CancelledError`` from the read is
    invented with nothing cancelled and is swallowed rather than delivered; and
    the result must be an exact ``str``, because a subclass's ``__format__`` runs
    when the message is built.
    """
    try:
        fault = fault_class_of(exc) if isinstance(exc, Exception) else _INVENTED_CANCELLATION
    except asyncio.CancelledError:
        return UNREPRESENTABLE_FAULT_CLASS
    return fault if type(fault) is str else UNREPRESENTABLE_FAULT_CLASS


def _internal(definition: ToolDefinition, exc: BaseException) -> ToolResult:
    """Describe a broken tool without quoting it — never ``str(exc)`` (ADR-0029 §3)."""
    return ToolResult(
        outcome=ToolOutcome.FAILED,
        failure=ToolFailure(
            kind=ToolFailureKind.INTERNAL,
            message=f"{_fault_class(exc)} escaped tool {definition.id!r}",
        ),
    )


def invoker_over(
    tools: Iterable[tuple[ToolDefinition, FakeToolImplementation]] = (),
    *,
    trail: FakeAuditTrail | None = None,
) -> tuple[FakeToolInvoker, FakeAuditTrail]:
    """Build a ``FakeToolInvoker`` and the trail it claims through.

    The arrangement a consumer's fixture wants since ADR-0192 §1 made the consume
    unconditional: the invoker holds the trail's **ledger** face, and the test
    holds the trail so it can record the authorisations its calls carry.

    Pass ``trail`` where the consumer already has one — a runner records every
    decision into its own trail before executing, so handing the seam that same
    object is what production does and is what keeps a consumer's test on the
    production path rather than around it.

    Args:
        tools: ``(definition, callable)`` pairs to register immediately.
        trail: The trail to claim through **and admit through** — one object as
            both faces, as the composition root wires it (ADR-0192 §2, ADR-0194
            §5). A fresh one is opened where none is given, and a fresh one carries
            no ceiling, so it admits every call. Pass a ``FakeAuditTrail`` built
            with a currency and a ceiling where the ceiling is what a test is
            about.

    Returns:
        The invoker, and the trail behind it.
    """
    behind = FakeAuditTrail() if trail is None else trail
    # One object as both faces, which is what the composition root does (ADR-0194
    # §5): two holders over the same rows could disagree about a total. A trail
    # built with no ceiling admits everything unconditionally (ADR-0194 §1, §3),
    # so a fixture that cares about the ceiling passes a configured `trail`.
    return FakeToolInvoker(tools, ledger=behind, gate=behind), behind


async def authorised(trail: FakeAuditTrail, call: ToolCall) -> ToolCall:
    """Record ``call``'s decision in ``trail``, and return the call unchanged.

    What ``StepRunner`` does in front of every execution, available to a test that
    drives the seam directly. ADR-0192 §1 has the ledger require the decision it is
    passed to equal the one the store holds under that id, so a call whose
    authorisation was never recorded is refused ``UnrecordedAuthorisationError``
    before the callable — correctly, and unhelpfully for a test about something
    else.

    Args:
        trail: The trail the invoker claims through.
        call: The authorised call about to be invoked.

    Returns:
        ``call``, so this reads inline at the invocation site.
    """
    await trail.record(call.decision)
    return call


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


async def _captured(
    append: Callable[[], Coroutine[Any, Any, ToolInvocation]],
) -> ToolInvocation | BaseException:
    """Return what ``append()`` produced, or the exception it raised, as a value.

    **``append`` is called here, inside the task, and not by the caller.** Nothing
    makes a conforming ``InvocationLedger`` method a native ``async def`` — a
    plain function returning a coroutine satisfies the Protocol — and such a
    function can raise *before* it returns anything to await. Called in the
    caller's frame that raise would miss the capture entirely: on the claim path
    it would reach ``invoke`` untranslated instead of as the ``AuditError``
    ADR-0192 §1 requires, and on the completion path it would replace a
    ``ToolResult`` the tool had already produced and leave the claim open (§3).

    See :func:`_driven` for why a failure leaves this task as a value: a
    ``BaseException`` propagating out of a task is re-raised into the event loop
    (ADR-0031 §4), and the frame that owes ADR-0192 §3's diagnostic would never
    resume to write it.
    """
    try:
        return await append()
    except BaseException as exc:
        # Every class, because the caller decides what each one means and this
        # frame decides nothing (ADR-0192 §1, §3).
        return exc


async def _driven(
    append: Callable[[], Coroutine[Any, Any, ToolInvocation]],
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
        append: Makes the ledger call. Invoked inside the task, so a synchronous
            factory that raises before returning a coroutine is captured like any
            other failure rather than escaping this frame.

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
    task = asyncio.ensure_future(_captured(append))
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


def _diagnose(operation: str, error: BaseException, outcome: ToolOutcome | None = None) -> None:
    """Report an append failure in enumerated fields only (ADR-0192 §3).

    Three fields exhaust it: the operation, always; the fault class, where the
    exception is an ``Exception``; and the outcome, where the operation is a
    completion. No instance, no message, no cause chain and no identifier.

    **The classifier is unguarded and the emitter is guarded**, for the reason
    `ai_assistant.tools.consume` states at length. ``fault_class_of`` lets a
    ``BaseException`` from the ``__name__`` read propagate by design, and ADR-0192
    §3 has it "leave the emitting frame" with no diagnostic standing in for it, so
    it leaves before the emission is reached and the call site disposes of it. A
    broken *emitter* is a different subject §3 does not discuss: an ``Exception``
    from the logging pipeline costs the diagnostic and never the ``ToolResult``,
    and so does a ``CancelledError`` — both call sites read the cancellation count
    before this, and the emission is synchronous, so one raised by a processor is
    invented with nothing cancelled (ADR-0031 §2).

    Raises:
        BaseException: Whatever the class read raised, and whatever the emitter
            raised that is not an ``Exception`` — neither inspected, annotated nor
            chained on the way out.
    """
    fields: dict[str, object] = {"operation": operation}
    if isinstance(error, Exception):
        fields["fault_class"] = fault_class_of(error)
    if outcome is not None:
        fields["outcome"] = outcome
    with contextlib.suppress(Exception, asyncio.CancelledError):
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
    appended, absorbed = await _driven(
        lambda: ledger.complete_invocation(
            claim_id=claim.id,
            outcome=completion.outcome,
            incurred_cost=completion.incurred_cost,
            failure_kind=completion.failure_kind,
        )
    )
    cancelled = absorbed or _pending_cancellations() > entered_with
    if not isinstance(appended, BaseException):
        return _Appended(None, cancelled)
    error = appended

    try:
        _diagnose(COMPLETION, error, completion.outcome)
    except BaseException as exc:
        # The classifier's own failure becomes what this path disposes of, rather
        # than escaping past the disposition (ADR-0192 §3). Rebound, not annotated.
        error = exc
    # Re-read: the emission is the only thing between the sample above and here,
    # and a processor is arbitrary code that can cancel this task. ADR-0192 §1's
    # branch turns on the count whoever moved it, and a request left unhonoured
    # would leave the executor an ordinary error for a call the loop had
    # cancelled.
    cancelled = cancelled or _pending_cancellations() > entered_with
    if propagating or cancelled:
        return _Appended(error, cancelled)
    if isinstance(error, asyncio.CancelledError | Exception):
        return _Appended(None, False)
    raise error


_CAUSE_SLOT: Final[GetSetDescriptorType] = BaseException.__dict__["__cause__"]
"""``BaseException``'s own ``__cause__`` descriptor — see ``ai_assistant.tools.consume``.

Writing through it runs none of a collaborator's own code: no ``__setattr__``
override and no ``__cause__`` property of the subclass, and it cannot raise for an
exception value.
"""


def _displaced_cause(exception: BaseException) -> BaseException | None:
    """Read the cause slot so the raising frame can retain what the write displaces.

    See ``ai_assistant.tools.consume``. The write enters none of the object's own
    code but can *release* some — a displaced cause finalised by this very write
    could reclaim the slot from its ``__del__`` — and retaining it removes the
    trigger rather than detecting it.
    """
    return cast("BaseException | None", _CAUSE_SLOT.__get__(exception))


def _attach_cause(exception: BaseException, cause: BaseException) -> None:
    """Attach ``cause`` to ``exception`` without entering the object's own code."""
    _CAUSE_SLOT.__set__(exception, cause)


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
    appended, absorbed = await _driven(lambda: ledger.claim_invocation(decision=decision))
    cancelled = absorbed or _pending_cancellations() > entered_with

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
    try:
        _diagnose(CLAIM, error)
    except BaseException as exc:
        # As on the completion path (ADR-0192 §3).
        error = exc
    # Re-read: the emission is the only thing between the sample above and here,
    # and a processor is arbitrary code that can cancel this task. ADR-0192 §1's
    # branch turns on the count whoever moved it, and a request left unhonoured
    # would leave the executor an ordinary error for a call the loop had
    # cancelled.
    cancelled = cancelled or _pending_cancellations() > entered_with
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


async def _admitted_call(
    *,
    gate: SpendGate,
    estimate: ToolCost,
    definition: ToolDefinition,
    timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0029 §4, ADR-0194 §3)
    act: Callable[[timedelta], Awaitable[ToolResult]],
) -> ToolResult:
    """Admit this invocation, run ``act`` in what is left of ``timeout``, release.

    ADR-0194 §3, re-implemented here rather than imported for the reason
    everything in this module is: the fake may not import ``ai_assistant.tools``.
    The admission is awaited **inside** the caller's deadline and ``act`` is given
    the remainder of that same deadline, so the two are one window rather than two.

    A refusal leaves as the gate raised it — nothing here catches, wraps or
    annotates one, which is what keeps ADR-0194 §4's payload-free rule true at the
    seam that could undo it.
    """
    loop = asyncio.get_running_loop()
    expires_at = loop.time() + timeout.total_seconds()
    try:
        async with asyncio.timeout_at(expires_at):
            handle = await gate.admit_invocation(estimate=estimate)
    except TimeoutError:
        # ADR-0029 §4's existing rule, unchanged: `invoke` was entered and
        # suspended in its own pre-call work, and nothing states which await the
        # expiry landed in (ADR-0034 §1). No claim was appended and no handle
        # exists, so there is nothing to complete and nothing to release.
        return _expired(definition, timeout)
    try:
        remaining = expires_at - loop.time()
        if remaining <= 0:
            return _expired(definition, timeout)
        return await act(timedelta(seconds=remaining))
    finally:
        # Synchronous, so unwinding under a cancellation cannot lose it, and it
        # raises nothing — a `finally` that raised would replace the call's own
        # outcome with a book-keeping failure (ADR-0194 §5).
        gate.release_admission(handle)


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
        # **The cancellation this frame caught is what leaves, carrying the
        # append's failure as its cause** — see `ai_assistant.tools.consume`.
        # ADR-0192 §3 names that exception and `ToolInvoker.invoke`'s contract
        # re-raises what it was already raising, so its identity survives a
        # completion that failed. `_attach_cause` writes through
        # `BaseException`'s own descriptor rather than assigning the attribute,
        # so a tool's `__setattr__` or `__cause__` property never runs.
        # Bound and never read, deliberately — see `_displaced_cause`.
        displaced = _displaced_cause(cancellation)  # noqa: F841
        _attach_cause(cancellation, appended.failure)
        raise

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
    "authorised",
    "invoker_over",
    "succeeds",
]
