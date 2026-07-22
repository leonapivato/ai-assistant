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
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

from pydantic import ValidationError

from ai_assistant.core.errors import ToolBindingError, ToolRegistrationError
from ai_assistant.core.types import (
    ToolCall,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from ai_assistant.core.types import FrozenJson, ToolDefinition


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

    def __init__(self, tools: Iterable[tuple[ToolDefinition, FakeToolImplementation]] = ()) -> None:
        """Create an invoker holding ``tools``.

        Raises:
            ToolRegistrationError: If ``tools`` contains two definitions sharing
                an id.
        """
        self._bindings: dict[str, _Binding] = {}
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

        Raises:
            ValueError: If ``timeout`` is not a strictly positive ``timedelta``.
            ToolBindingError: If the call does not survive revalidation, names
                an unbound id, carries a definition unequal to this fake's own,
                or is not authorised by its decision.
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
        return await self._run(binding, checked, timeout)

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


__all__ = ["FakeToolImplementation", "FakeToolInvoker", "succeeds"]
