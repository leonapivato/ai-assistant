"""An in-memory tool registry that is also the invocation seam (ADR-0016, ADR-0029).

The registry holds declarations, answers questions about them, ranks nothing,
and runs the one callable each declaration is bound to. Population is
deliberately *not* on either Protocol — :meth:`InMemoryToolRegistry.register`
and :meth:`InMemoryToolRegistry.deregister` are this class's own API, because
nothing outside `tools` has business owning the registration lifecycle
(ADR-0016 §5). ADR-0016 §5 predicted the shape change this module now makes:
"When invocation lands it will change how `tools/` is populated, which is then a
`tools/` change and not a breaking one."

**One object, two Protocols.** ADR-0029 §1 requires that an id be invocable *if
and only if* it is registered, and makes that checkable by keeping ``all_tools``
and the invocable set the same set. Two tables keyed by the same id could be
rebound independently, which is ADR-0016 §7's named failure — "executing an
implementation whose risk declaration is not the one the user approved" — so
there is one mapping here from id to ``(definition, callable)``, and both faces
read it.

In-memory only, rebuilt from scratch each run. A ``ToolDefinition`` is Tier 2
configuration declared by code, not personal data, so there is no export or
delete obligation here as there is for ``MemoryStore`` and ``PlanStore``
(ADR-0016 §6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ai_assistant.core.errors import ToolBindingError, ToolRegistrationError
from ai_assistant.core.types import ToolCall, ToolDefinition
from ai_assistant.tools.invocation import ToolImplementation, run_bound_call

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ai_assistant.core.types import ToolResult


def _revalidated(tool: ToolDefinition) -> ToolDefinition:
    """Rebuild ``tool`` through validation, detached from the caller's instance.

    A definition can reach here in a state the type would refuse to construct,
    because ``frozen=True`` does not stop ``__dict__`` writes. Copying would
    preserve that state; round-tripping rejects it.

    **This is validation, not authentication.** It answers "could this have been
    constructed?", never "is this what the author declared?" — so a definition
    tampered into a *still-valid* state passes. See the class docstring.

    Raises:
        ValidationError: If the incoming definition violates the type's rules.
    """
    return ToolDefinition.model_validate(tool.model_dump())


def checked_timeout(timeout: object) -> timedelta:
    """Reject a deadline ``invoke`` could not enforce (ADR-0029 §4).

    **The annotation is not the enforcement.** Python does not check a parameter
    annotation at runtime and this argument crosses a Protocol boundary from a
    possibly untyped or dynamically-wired caller, so the guard is total over the
    value. That is ADR-0026 §2's rule for a clock reading and ADR-0021 §4's for
    ``recent``'s ``limit``, and the concrete reason is the same: the natural
    implementation leaks. ``asyncio.timeout(None)`` is no deadline at all, in
    the one method whose contract is that there is always one.

    **Strictly positive, and not "expired means do not call".** A zero or
    negative duration is refused rather than treated as an instantly-expired
    deadline, because expiry is delivered by the event loop at an await point: a
    callable performing a synchronous side effect before its first ``await``
    would already have acted. Refusing the value never creates the coroutine,
    which is the only placement that holds for every tool.

    Raises:
        ValueError: If ``timeout`` is not a ``timedelta``, or is not strictly
            positive.
    """
    if not isinstance(timeout, timedelta):
        msg = f"timeout must be a timedelta, got {type(timeout).__name__}"
        raise ValueError(msg)
    if timeout <= timedelta(0):
        msg = f"timeout must be strictly positive, got {timeout}"
        raise ValueError(msg)
    return timeout


def revalidated_call(call: ToolCall) -> ToolCall:
    """Rebuild ``call`` through validation, detached from the caller's instance.

    The **first** of ADR-0029 §2's three checks, and its position is part of the
    rule. ``frozen=True`` refuses ``call.request = ...`` and does nothing about
    ``call.__dict__["request"] = ...``, and that bypass is inside this
    repository's threat model rather than outside it (ADR-0018 §3, ADR-0021 §4).
    A ``__dict__`` write can leave ``parameters`` holding a value ``FrozenJson``
    would never have accepted, and ``authorises`` compares a digest that
    canonicalises that mapping to JSON — so checking authorisation first would
    raise a raw serialisation error out of a method whose contract is that it
    answers a question, after the executor has already committed its
    ``→ RUNNING`` claim. Revalidating first turns that input into a rejection.

    Raises:
        ToolBindingError: If the mutated call is one the type would refuse to
            construct, carrying the ``ValidationError`` as its cause.
    """
    try:
        return ToolCall.model_validate(call.model_dump())
    except ValidationError as exc:
        msg = "the call did not survive revalidation, so it is not the call that was authorised"
        raise ToolBindingError(msg) from exc


@dataclass(frozen=True, slots=True)
class _Binding:
    """One id's declaration and the callable that satisfies it.

    A single record rather than two dicts, so an id cannot come to hold a
    declaration and a callable that were registered apart (ADR-0029 §1).
    """

    definition: ToolDefinition
    implementation: ToolImplementation


class InMemoryToolRegistry:
    """A tool registry backed by a dict, structurally a ``ToolRegistry`` and a ``ToolInvoker``.

    Both faces over **one** mapping, which is what makes ADR-0029 §1's
    biconditional true by construction rather than by care: the ids
    :meth:`all_tools` reports and the ids :meth:`invoke` will act on are read
    from the same dict, so they cannot come apart.

    Ids are **spent on first use**: once an id has been registered it is bound
    to that definition for the life of this registry, and deregistering does not
    free it. See :meth:`register`.

    Definitions are **re-validated** on the way in and copied on the way out.
    That is not redundant with ``frozen=True``, for the reason ADR-0014 gives
    about stored plans: freezing refuses ``tool.risk_level = ...`` but not
    ``tool.__dict__["risk_level"] = ...``. Since that bypass is part of the
    threat model here — tool metadata is a security control — it has to be
    closed on both sides. Copying alone would preserve whatever state the object
    arrived in, so a definition mutated *before* registration (say
    ``side_effecting`` flipped to ``False`` while ``discloses`` stays non-empty)
    would be stored as authoritative despite being one the type would refuse to
    construct. Round-tripping through validation rebuilds it under the same
    rules, as ``FakePlanStore`` does for a step transition. Re-validation is the
    current strategy for ADR-0018 §4's postcondition — *what is stored is valid
    and detached* — rather than the postcondition itself; a trusted minting
    factory would satisfy it too.

    **What this does not catch.** Re-validation only rejects definitions that
    could not have been constructed. A definition tampered into a still-valid
    state — ``risk_level`` moved from ``CRITICAL`` to ``LOW`` — rebuilds
    successfully, because ``LOW`` is valid and this registry holds no trusted
    original to compare against. Such a definition is refused only when its id
    is *already bound* to a different one, which is the conflict rule below, not
    this. **Under a fresh id it is accepted, and nothing here detects it.**
    Closing that needs a provenance boundary — a signature, a minting factory,
    or the pinned digest issue #54 proposes for the approval path — which this
    contract does not provide (ADR-0018 §4).

    **Not thread-safe, by design.** The system composes on one event loop
    (CONTRIBUTING, "Async for all I/O"), and :meth:`register`/:meth:`deregister`
    are synchronous with no ``await`` inside, so they cannot interleave with the
    async queries on that loop. Registration from several OS threads would race
    the spent-id check against the write; a host that wants that must serialise
    it, and a lock here would otherwise be cost with no reader.
    """

    def __init__(self, tools: Iterable[tuple[ToolDefinition, ToolImplementation]] = ()) -> None:
        """Create a registry, optionally registering ``tools`` in order.

        Args:
            tools: ``(definition, callable)`` pairs to register immediately, as
                a convenience for composition roots that know the full set up
                front. A pair rather than a definition alone because ADR-0029
                §1's biconditional has no room for a declared-but-unrunnable id.

        Raises:
            ToolRegistrationError: If ``tools`` contains two definitions sharing
                an id.
        """
        self._live: dict[str, _Binding] = {}
        self._spent: dict[str, _Binding] = {}
        for tool, implementation in tools:
            self.register(tool, implementation)

    def register(self, tool: ToolDefinition, implementation: ToolImplementation, /) -> None:
        """Bind ``tool`` and the callable that satisfies it to its id, permanently.

        Re-registering the *same* definition **and the same callable** under a
        live id is idempotent, so a composition root may run twice without
        special-casing. Anything else is refused:

        - a **different** definition under a used id would silently rewrite a
          security control — swapping ``risk_level=CRITICAL`` for ``LOW`` under
          an id a policy already trusts;
        - a **different callable** under a used id is refused for the same
          reason one level down: the declaration would still read as the one
          approved while different code ran behind it, which is precisely what
          binding the two together is for;
        - **any** registration under a *deregistered* id is refused too, even an
          identical one. Deregistration is revocation, not renaming. Were an id
          reusable, it could be rebound between a permission decision and the
          step that executes it: the user approves a ``REVERSIBLE`` send, an
          ``IRREVERSIBLE`` definition takes the name, and both the
          ``approval_ref`` and the ``bound_tool`` id still read as consistent.

        Raises:
            ToolRegistrationError: If the id is already bound to a different
                definition or callable, or has been deregistered.
            ValidationError: If the definition violates the type's own rules,
                which a ``__dict__`` write can leave it doing.
        """
        binding = _Binding(_revalidated(tool), implementation)

        previous = self._spent.get(binding.definition.id)
        if previous is None:
            self._live[binding.definition.id] = binding
            self._spent[binding.definition.id] = binding
            return

        if binding.definition.id not in self._live:
            msg = (
                f"tool id {binding.definition.id!r} was deregistered and cannot be reused: "
                "deregistration is revocation, so a definition rebound to a spent id "
                "could be substituted for the one a permission decision approved"
            )
            raise ToolRegistrationError(msg)

        if previous.definition != binding.definition:
            msg = (
                f"tool id {binding.definition.id!r} is already registered with a different "
                "definition; tool metadata is a security control, so it cannot be "
                "overwritten in place"
            )
            raise ToolRegistrationError(msg)

        if previous.implementation is not binding.implementation:
            msg = (
                f"tool id {binding.definition.id!r} is already bound to a different "
                "implementation; rebinding the callable would leave the approved "
                "declaration in place while other code ran behind it"
            )
            raise ToolRegistrationError(msg)

    def deregister(self, tool_id: str) -> bool:
        """Revoke a tool, spending its id for good.

        Returns:
            ``True`` if a live tool was removed, ``False`` if none had that id
            (including an id already deregistered).
        """
        return self._live.pop(tool_id, None) is not None

    def _definitions(self) -> list[ToolDefinition]:
        """Return every live declaration, ordered by id, still attached."""
        return sorted(
            (binding.definition for binding in self._live.values()), key=lambda tool: tool.id
        )

    async def get(self, tool_id: str) -> ToolDefinition | None:
        """Return the definition registered as ``tool_id``, or ``None``."""
        stored = self._live.get(tool_id)
        return None if stored is None else stored.definition.model_copy(deep=True)

    async def find(self, capability: str) -> list[ToolDefinition]:
        """Return every live tool advertising ``capability``, ordered by id."""
        return [
            tool.model_copy(deep=True)
            for tool in self._definitions()
            if tool.capability == capability
        ]

    async def capabilities(self) -> tuple[str, ...]:
        """Return the advertised capability vocabulary, sorted and de-duplicated."""
        return tuple(sorted({binding.definition.capability for binding in self._live.values()}))

    async def all_tools(self) -> list[ToolDefinition]:
        """Return every live definition, ordered by id."""
        return [tool.model_copy(deep=True) for tool in self._definitions()]

    async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0029 §4); wrapping it outside would cancel the invoker mid-await
        """Run ``call`` against this registry's own binding for it (ADR-0029 §1, §2).

        Three checks, in this order, before the callable is reached; each reads
        the revalidated copy and never the argument.

        See :meth:`~ai_assistant.core.protocols.ToolInvoker.invoke` for the
        contract this satisfies.

        Raises:
            ValueError: If ``timeout`` is not a strictly positive ``timedelta``.
            ToolBindingError: If the call does not survive revalidation, names
                an unbound id, carries a definition unequal to this registry's
                own, or is not authorised by its decision.
            CancelledError: If the invoking task is cancelled from outside.
        """
        checked_timeout(timeout)
        checked = revalidated_call(call)

        binding = self._live.get(checked.request.tool.id)
        if binding is None:
            msg = (
                f"tool id {checked.request.tool.id!r} is not bound in this registry, "
                "so there is nothing to invoke"
            )
            raise ToolBindingError(msg)

        # The registry is the only holder of an untampered original, and this is
        # the only place all three declarations meet. ADR-0018 §4 recorded a
        # definition "tampered into a still-valid state" as a gap it could not
        # close; this is where it closes.
        if binding.definition != checked.request.tool:
            msg = (
                f"the definition carried by the call for {checked.request.tool.id!r} is not the "
                "one this registry holds, so the thing about to run is not the thing declared"
            )
            raise ToolBindingError(msg)

        if not checked.decision.authorises(checked.request):
            msg = (
                f"decision {checked.decision.id!r} does not authorise this request, "
                "so the thing about to run is not the thing that was authorised"
            )
            raise ToolBindingError(msg)

        return await run_bound_call(
            binding.implementation,
            definition=binding.definition,
            call=checked,
            timeout=timeout,
        )
