"""Shared conformance suite for the ToolInvoker Protocol (ADR-0029).

Every ``ToolInvoker`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`ToolInvokerContract` and overrides the ``invoker`` fixture.

`InMemoryToolRegistry` and `FakeToolInvoker` implement the seam independently —
the fake cannot import the subsystem it stands in for — so this suite is what
stops the two drifting.

**Scope: what an implementation could get wrong.** ADR-0029's type-level rules —
an unauthorised ``ToolCall`` being unconstructable, ``ToolResult``'s cross-field
invariants, ``retryable``'s exhaustiveness, the key derivation itself — hold by
construction in ``core`` and are the same for every implementation, so they are
pinned in ``tests/core/test_tool_types.py`` where the types live rather than
re-asserted per subject. What lives here is everything ``invoke`` is free to get
wrong: the binding checks and their **order**, the deadline and its
classification, the provenance of a cancellation, and what reaches the callable.

The suite also requires its subject to present **both faces** of the registry,
which is how ADR-0029 §1's biconditional becomes checkable: an implementation
keeping a second table of callables fails ``test_the_invocable_set_is_exactly
_all_tools`` rather than passing review.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, NoReturn, Protocol

import pytest
import structlog.testing
from pydantic import ValidationError

from ai_assistant.core.errors import (
    AuditError,
    AuthorisationSpentError,
    ToolBindingError,
    UnrecordedAuthorisationError,
)
from ai_assistant.core.protocols import ToolInvoker, ToolRegistry
from ai_assistant.core.types import (
    UNREPRESENTABLE_FAULT_CLASS,
    ActionRequest,
    CostBasis,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    ToolCall,
    ToolCost,
    ToolDefinition,
    ToolFailureKind,
    ToolOutcome,
)
from ai_assistant.testing import APPEND_FAILED, CLAIM, COMPLETION, FakeAuditTrail

if TYPE_CHECKING:
    from collections.abc import (
        Awaitable,
        Callable,
        Coroutine,
        Mapping,
        MutableMapping,
        Sequence,
    )

    from ai_assistant.core.protocols import InvocationLedger
    from ai_assistant.core.types import FrozenJson, ToolInvocation, ToolResult
    from ai_assistant.testing import FakeToolImplementation

#: A fixed instant, so nothing here depends on how fast the suite runs.
AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

#: Long enough that a prompt tool finishes inside it on any machine the gate
#: runs on, short enough that the tests that *want* an expiry are quick.
PATIENT = timedelta(seconds=30)
BRIEF = timedelta(milliseconds=20)


class InvocableToolRegistry(ToolRegistry, ToolInvoker, Protocol):
    """Both faces, plus the one method this suite needs to arrange them.

    Requiring both is the point (ADR-0029 §1): the canonical implementation is
    one object over one mapping from id to ``(definition, callable)``, so the
    two sets this suite compares are read from the same place by construction.
    """

    def register(self, tool: ToolDefinition, implementation: FakeToolImplementation, /) -> None:
        """Bind a declaration and the callable that satisfies it."""
        ...

    @property
    def ledger(self) -> InvocationLedger:
        """The ledger this seam claims through, which the suite arranges."""
        ...


# --- builders -----------------------------------------------------------


def tool(tool_id: str = "smtp", **overrides: object) -> ToolDefinition:
    """Build a valid, side-effecting, non-``NATURAL`` definition.

    That base is deliberate: it is the declaration for which ADR-0029 §4's
    interrupted-call rule answers ``INDETERMINATE``, so a test wanting the
    ``FAILED`` half has to say so, rather than getting it by forgetting.
    """
    fields: dict[str, object] = {
        "id": tool_id,
        "capability": "send_email",
        "description": "Send an email.",
        "risk_level": RiskLevel.HIGH,
        "reversibility": Reversibility.IRREVERSIBLE,
        "side_effecting": True,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NONE,
    }
    fields.update(overrides)
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def read_only(tool_id: str = "inbox") -> ToolDefinition:
    """A tool with no side effect: ADR-0029 §4's ``FAILED`` branch."""
    return tool(
        tool_id,
        capability="read_email",
        side_effecting=False,
        reversibility=Reversibility.REVERSIBLE,
    )


def natural(tool_id: str = "upsert") -> ToolDefinition:
    """A side-effecting tool that is idempotent by nature: also ``FAILED``."""
    return tool(tool_id, idempotency=Idempotency.NATURAL)


def keyed(tool_id: str = "smtp", window: timedelta = timedelta(hours=24)) -> ToolDefinition:
    """A tool whose repeats are deduplicated by key inside ``window``."""
    return tool(tool_id, idempotency=Idempotency.KEYED, idempotency_window=window)


def gated(tool_id: str = "inbox", window: timedelta = timedelta(hours=24)) -> ToolDefinition:
    """A ``KEYED`` tool that is **not** side-effecting, so it is not spendable.

    The class the key cases below need since ADR-0192 §1 made a claim the consume:
    the key is derived from ``idempotency is KEYED`` alone
    (``ToolCall.idempotency_key``), while *spendability* is "side-effecting **and**
    not ``NATURAL``". So this tool derives a key exactly as ``keyed()`` does and
    §1 refuses no repetition under it — which is the read ADR-0016 §3 gates, and
    the only class under which "the same call twice" is still a thing ``invoke``
    will do.

    A **spendable** ``KEYED`` tool's repeat is governed by §1's conjunction
    instead, and is pinned where that conjunction is — not here.
    """
    return tool(
        tool_id,
        capability="read_email",
        side_effecting=False,
        reversibility=Reversibility.REVERSIBLE,
        idempotency=Idempotency.KEYED,
        idempotency_window=window,
    )


def call_for(
    definition: ToolDefinition,
    *,
    parameters: Mapping[str, FrozenJson] | None = None,
    step_id: str | None = "step-1",
    decision_id: str = "d-1",
    outcome: PermissionOutcome = PermissionOutcome.ALLOW,
) -> ToolCall:
    """Build an authorised call for ``definition``, through the sanctioned path.

    The decision goes through ``from_request`` rather than the constructor,
    because that is what the contract asks callers to use and it is what makes a
    call whose subject disagrees with its request unarrangeable here.
    """
    request = ActionRequest(
        tool=definition, parameters=parameters or {"to": "someone@example.com"}, step_id=step_id
    )
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=outcome, reason=f"because it is {outcome}"),
        id=decision_id,
        decided_at=AT,
    )
    return ToolCall(request=request, decision=decision)


class Spy:
    """A tool implementation that records what it was handed.

    The recording is what makes "the tool was never reached" assertable, which
    every binding-refusal test in this suite needs: asserting only that
    ``invoke`` raised would pass against an implementation that ran the callable
    and then checked.
    """

    def __init__(self, output: FrozenJson = None) -> None:
        """Record nothing yet; return ``output`` when called."""
        self.calls: list[tuple[dict[str, FrozenJson], str | None]] = []
        self._output = output

    async def __call__(
        self, parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        """Record the arguments and return the configured output."""
        self.calls.append((dict(parameters), idempotency_key))
        return self._output


class Raiser:
    """A tool implementation that raises whatever it was built with."""

    def __init__(self, exc: BaseException) -> None:
        """Raise ``exc`` on every call."""
        self._exc = exc
        self.calls = 0

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
    ) -> FrozenJson:
        """Raise, without ever awaiting anything."""
        self.calls += 1
        raise self._exc


class Returner:
    """A tool implementation returning a value ``FrozenJsonValue`` refuses."""

    def __init__(self, value: object) -> None:
        """Return ``value``, whatever it is."""
        self._value = value

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
    ) -> FrozenJson:
        """Return the unserialisable value, as a broken integration would."""
        return self._value  # type: ignore[return-value]  # the point of this double


class Slow:
    """A tool that waits long past any deadline the suite gives it."""

    def __init__(self) -> None:
        """Create the event that reports the callable has been entered."""
        self.entered = asyncio.Event()

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
    ) -> FrozenJson:
        """Sleep until cancelled."""
        self.entered.set()
        await asyncio.sleep(3600)
        return None


class Stubborn:
    """A tool that suppresses its cancellation and waits on an event.

    ADR-0029 §4's stated hole, made deterministic: ``asyncio.timeout`` does not
    return until the inner frame finishes unwinding, so a ``finally`` that
    awaits keeps ``invoke`` waiting past the deadline it was given. Pinning the
    *limit* is what stops an implementation quietly acquiring a watchdog, or a
    later reader assuming the deadline is a hard bound.
    """

    def __init__(self) -> None:
        """Create the event the test releases it with."""
        self.release = asyncio.Event()
        self.entered = asyncio.Event()

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
    ) -> FrozenJson:
        """Sleep, then refuse to unwind until the test says so."""
        try:
            self.entered.set()
            await asyncio.sleep(3600)
        finally:
            await self.release.wait()
        return None


class Swallower:
    """A tool that *catches* its cancellation and returns a value anyway.

    Nothing forces a callable to let a cancellation through, and this is the
    shape that makes an implementation trusting the returned value wrong in the
    worst available direction: a cancelled turn reported ``SUCCEEDED``, or a
    side-effecting call that outran its deadline reported as though it had met
    it. ``Stubborn`` does not cover it — that one delays its unwinding and still
    re-raises.
    """

    def __init__(self) -> None:
        """Create the event that reports the callable has been entered."""
        self.entered = asyncio.Event()
        self.swallowed = False

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
    ) -> FrozenJson:
        """Absorb whatever cancellation arrives and return normally."""
        self.entered.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.swallowed = True
        return {"done": True}


class KeyedTool:
    """A ``KEYED`` tool that deduplicates a repeat inside its declared window.

    The tool-side half of ADR-0029 §5's two-sided obligation: "a ``KEYED`` tool
    receiving the same key twice within its declared window performs the effect
    once and returns the first result". It keeps its own clock reading so the
    test can move time rather than wait.
    """

    def __init__(self, window: timedelta) -> None:
        """Deduplicate for ``window`` from each key's first use."""
        self._window = window
        self._seen: dict[str, tuple[datetime, int]] = {}
        self.now = AT
        self.effects = 0

    async def __call__(
        self, parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        """Perform the effect once per key per window, returning the first result."""
        assert idempotency_key is not None, "a KEYED tool must be handed a key"
        first = self._seen.get(idempotency_key)
        if first is not None and self.now - first[0] < self._window:
            return first[1]
        self.effects += 1
        self._seen[idempotency_key] = (self.now, self.effects)
        return self.effects


# --- the consume: ADR-0192 §1 and §3 ------------------------------------
#
# Everything below drives `invoke` through a ledger, which is the only thing that
# can observe the claim and the completion. The ledger under it is always the
# canonical `FakeAuditTrail` — the store side is the paired lane's suite, not this
# one — wrapped where a test needs an append held, failed, or failed *after* it
# committed.


class MovingClock:
    """A clock the test advances, for the window ADR-0192 §1 measures.

    The ledger stamps ``recorded_at`` from this and decides its admission rules on
    the same reading, so moving it is how a test reaches the far side of an
    ``idempotency_window`` without racing one.
    """

    def __init__(self, at: datetime = AT) -> None:
        """Read ``at`` until moved."""
        self.now = at

    def __call__(self) -> datetime:
        """Return the current reading."""
        return self.now


class Append:
    """How one ledger member behaves on the next call (a test's own arrangement)."""

    def __init__(self) -> None:
        """Behave exactly like the ledger under it, until arranged otherwise."""
        #: Set the moment the append is entered.
        self.entered = asyncio.Event()
        #: Awaited before the append proceeds, where a test holds one.
        self.hold: asyncio.Event | None = None
        #: Raised instead of, or after, the real append.
        self.error: BaseException | None = None
        #: Whether the real append runs before ``error`` is raised. ``True`` is
        #: ADR-0192 §1's and §3's commit-state case: the row stands and the append
        #: raised, and no caller may tell that apart from a write that never landed.
        self.commits = False
        #: How many times this member has been entered.
        self.calls = 0


class DrivenLedger:
    """An ``InvocationLedger`` a test can hold, fail, or fail after it committed.

    **A wrapper rather than a second store.** Every rule about *what a ledger
    does* is the paired lane's, pinned in its own conformance suite; what this
    suite needs is a ledger whose **timing** and **failure** the test owns, so the
    seam's own clauses — the shield, the absorption, the commit-state split, the
    diagnostic — become observable.

    ADR-0192 §3 decides absorption "by class, not by origin", so raising the
    exception from here is a faithful driver for a ledger that raised it, whatever
    produced it — a refusal, a guard's rejection, a store that would not write, or
    an exception an injected clock callable raised and the ledger propagated
    unwrapped (ADR-0026 §2).
    """

    def __init__(self, inner: FakeAuditTrail) -> None:
        """Delegate to ``inner``, under the two arrangements below."""
        self.inner = inner
        self.claim = Append()
        self.completion = Append()

    async def _through(
        self, append: Append, real: Callable[[], Awaitable[ToolInvocation]]
    ) -> ToolInvocation:
        """Run ``real`` under ``append``'s arrangement."""
        append.calls += 1
        append.entered.set()
        if append.hold is not None:
            await append.hold.wait()
        if append.error is not None and not append.commits:
            raise append.error
        row = await real()
        if append.error is not None:
            raise append.error
        return row

    async def claim_invocation(self, *, decision: PermissionDecision) -> ToolInvocation:
        """Append a claim under ``decision``, or behave as arranged."""
        return await self._through(
            self.claim, lambda: self.inner.claim_invocation(decision=decision)
        )

    async def complete_invocation(
        self,
        *,
        claim_id: str,
        outcome: ToolOutcome,
        incurred_cost: ToolCost,
        failure_kind: ToolFailureKind | None = None,
    ) -> ToolInvocation:
        """Append the completion of ``claim_id``, or behave as arranged."""
        return await self._through(
            self.completion,
            lambda: self.inner.complete_invocation(
                claim_id=claim_id,
                outcome=outcome,
                incurred_cost=incurred_cost,
                failure_kind=failure_kind,
            ),
        )


async def rows(trail: FakeAuditTrail) -> list[ToolInvocation]:
    """Every invocation row the trail holds, in the order the read returns them.

    That order is ``recent``'s and not the ledger's append order (ADR-0192 §2), so
    nothing below reads a row *by position*: the two kinds are told apart by
    :attr:`ToolInvocation.completes`, which is what the shape's own discriminator
    is for.
    """
    return [each.invocation for each in await trail.export_invocations()]


async def claims(trail: FakeAuditTrail) -> list[ToolInvocation]:
    """Every claim row the trail holds, completed or not."""
    return [each for each in await rows(trail) if each.completes is None]


async def completions(trail: FakeAuditTrail) -> list[ToolInvocation]:
    """Every completion row the trail holds."""
    return [each for each in await rows(trail) if each.completes is not None]


def appended(captured: Sequence[Mapping[str, Any]]) -> list[dict[str, object]]:
    """The append-failure diagnostics among ``captured``, fields and all.

    ``capture_logs`` adds its own ``event`` and ``log_level`` keys; both are
    dropped so a test can assert the ADR-0192 §3 matrix **field by field**,
    including that an absent field is absent rather than merely unchecked.
    """
    return [
        {key: value for key, value in each.items() if key not in {"event", "log_level"}}
        for each in captured
        if each.get("event") == APPEND_FAILED
    ]


class NameRaises(type):
    """A metaclass that refuses to be named, raising an ``Exception`` when asked.

    ``fault_class_of`` guards the ``__name__`` read precisely because "total" has
    to mean it: a metaclass may override the access and raise, and either would
    otherwise take down the diagnostic together with the fault it was recording.
    """

    def __getattribute__(cls, name: str) -> object:
        """Raise on ``__name__`` and behave normally on everything else."""
        if name == "__name__":
            msg = "the metaclass refuses to be named"
            raise RuntimeError(msg)
        return super().__getattribute__(name)


async def _settled(cycles: int = 4) -> None:
    """Let the loop deliver whatever is pending, without sleeping on a clock.

    A cancellation is delivered at the invoking task's next suspension point, so
    a test that asserts "still waiting" has to give the loop a turn first —
    deterministically, and never by racing a duration.
    """
    for _ in range(cycles):
        await asyncio.sleep(0)


async def invoked(
    invoker: InvocableToolRegistry,
    trail: FakeAuditTrail,
    call: ToolCall,
    *,
    timeout: timedelta = PATIENT,  # noqa: ASYNC109 — relayed to the seam, which owns it
) -> ToolResult:
    """Record ``call``'s authorisation if the trail has not got it, then invoke.

    What ``StepRunner`` does in front of every execution, and what ADR-0192 §1 now
    makes a precondition of reaching the callable at all: the ledger requires the
    decision it is passed to equal the one the store holds under that id, so an
    unrecorded authorisation is refused before the tool. The cases *about* that
    refusal call ``invoke`` directly; every case about something else goes through
    here.

    **Recorded once per decision, not once per call.** A trail refuses a second
    ``record`` under one id, and a decision legitimately backs more than one act
    where ADR-0192 §1 admits one — so this mirrors the runner, which records the
    ruling once and may then execute under it again.
    """
    if await trail.get(call.decision.id) is None:
        await trail.record(call.decision)
    return await invoker.invoke(call, timeout=timeout)


class SynchronousFactory:
    """A registration that is **not** a native ``async def``.

    Nothing makes one: the callable shape is satisfied by any object returning an
    awaitable, so a plain function's body runs at the **call**, before the
    coroutine it hands back is ever awaited. That is what makes ADR-0192 §1's "the
    claim is appended immediately before the callable is entered" a statement about
    *calling* and not only about awaiting — an implementation that obtains the
    coroutine in order to hold it across the claim has already run this body.
    """

    def __init__(self) -> None:
        """Record nothing yet."""
        self.entered = 0

    def __call__(
        self, parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> Coroutine[Any, Any, FrozenJson]:
        """Run the synchronous half **now**, and return the awaitable half."""
        self.entered += 1
        recorded = dict(parameters)

        async def _acting() -> FrozenJson:
            return recorded.get("to")

        return _acting()


class ToolInvokerContract:
    """Behaviour every ``ToolInvoker`` implementation must exhibit."""

    @pytest.fixture
    def consuming(self) -> Callable[[InvocationLedger], InvocableToolRegistry]:
        """Return a factory building an empty invoker over ``ledger``.

        A factory rather than a built subject, because half the consume cases need
        the ledger *wrapped* — held on a barrier, made to fail, made to fail after
        it committed — and an invoker is handed its ledger at construction.
        """
        raise NotImplementedError

    @pytest.fixture
    def invoker(self) -> InvocableToolRegistry:
        """The subject, and it is **ledger-bearing** like every other invoker.

        Since ADR-0192 §1 made the consume unconditional there is no ledger-free
        ``ToolInvoker`` to be had, so this suite has one subject rather than an
        ordinary one beside a consuming one — a second, non-conforming fixture
        would leave the ordinary subject unbound by the new obligations while they
        were pinned on a different object.

        Overridden by each binding subclass and **taking no other fixture**, which
        is what lets ``tests/core/test_protocol_triad.py`` evaluate it and see the
        canonical fake come out (CONTRIBUTING, "Adding a Protocol"). The trail is
        read back off the subject rather than injected beside it, for the same
        reason the composition root wires one object: two would leave the seam
        claiming against a store the test never recorded into.
        """
        raise NotImplementedError

    @pytest.fixture
    def trail(self, invoker: InvocableToolRegistry) -> FakeAuditTrail:
        """The trail the subject claims through, read back off the subject."""
        ledger = invoker.ledger
        assert isinstance(ledger, FakeAuditTrail), (
            "this suite arranges authorisations through the trail the subject holds"
        )
        return ledger

    # --- §1: one registry, two faces ------------------------------------

    async def test_the_invocable_set_is_exactly_all_tools(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The biconditional, asserted as set equality rather than exhorted.

        An implementation keeping a second table of callables — two mappings
        that could be rebound independently — fails here rather than at review.
        """
        invoker.register(tool("alpha"), Spy())
        invoker.register(tool("zulu"), Spy())

        declared = {each.id for each in await invoker.all_tools()}
        invocable = set()
        for each in await invoker.all_tools():
            # A decision id apiece: two tools authorised under one id is not a
            # trail this store could hold, and since ADR-0192 §1 the seam reads it.
            result = await invoked(
                invoker, trail, call_for(each, decision_id=f"d-{each.id}"), timeout=PATIENT
            )
            assert result.outcome is ToolOutcome.SUCCEEDED
            invocable.add(each.id)

        assert invocable == declared == {"alpha", "zulu"}

        unregistered = tool("never-registered")
        with pytest.raises(ToolBindingError):
            await invoked(invoker, trail, call_for(unregistered), timeout=PATIENT)

    async def test_an_unbound_id_is_refused(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """Nothing is bound, so there is nothing to invoke."""
        with pytest.raises(ToolBindingError, match="smtp"):
            await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

    async def test_a_tampered_but_still_valid_definition_is_refused(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0018 §4's named gap, closing here.

        ``risk_level`` moved from ``CRITICAL`` to ``LOW`` rebuilds successfully,
        so no amount of re-validation catches it. The registry is the only holder
        of an untampered original, and this seam is the only place all three
        declarations meet.
        """
        spy = Spy()
        invoker.register(tool(risk_level=RiskLevel.CRITICAL), spy)

        # A wholly valid call — about a *different* declaration under the same id.
        downgraded = call_for(tool(risk_level=RiskLevel.LOW))

        with pytest.raises(ToolBindingError):
            await invoked(invoker, trail, downgraded, timeout=PATIENT)
        assert spy.calls == [], "the callable must not be reached"

    # --- §2: refused again at the seam ----------------------------------

    async def test_parameters_swapped_after_construction_are_refused(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """``frozen=True`` does not survive a ``__dict__`` write.

        Construct a call approving one recipient, replace ``parameters`` with a
        valid frozen mapping naming another, and a seam checking only the
        definition would execute the second under the first's approval.
        """
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool(), parameters={"to": "approved@example.com"})

        swapped = ActionRequest(
            tool=tool(),
            parameters={"to": "elsewhere@example.com"},
            step_id=call.request.step_id,
        )
        call.__dict__["request"] = swapped

        with pytest.raises(ToolBindingError):
            await invoked(invoker, trail, call, timeout=PATIENT)
        assert spy.calls == []

    async def test_a_replaced_decision_is_refused(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """A decision about a different payload cannot authorise this one."""
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool(), parameters={"to": "approved@example.com"})
        other = call_for(tool(), parameters={"to": "elsewhere@example.com"}, decision_id="d-2")
        call.__dict__["decision"] = other.decision

        with pytest.raises(ToolBindingError):
            await invoked(invoker, trail, call, timeout=PATIENT)
        assert spy.calls == []

    async def test_a_substituted_definition_is_refused(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The declaration on the call is rewritten after it was authorised."""
        spy = Spy()
        invoker.register(tool(risk_level=RiskLevel.CRITICAL), spy)
        call = call_for(tool(risk_level=RiskLevel.CRITICAL))

        object.__setattr__(call.request.tool, "risk_level", RiskLevel.LOW)

        with pytest.raises(ToolBindingError):
            await invoked(invoker, trail, call, timeout=PATIENT)
        assert spy.calls == []

    async def test_a_malformed_parameter_mutation_is_a_binding_error_from_revalidation(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The **order** of the checks, which only a malformed mutation distinguishes.

        ``authorises`` compares ``parameters_digest``, which canonicalises the
        mapping to JSON. Run before revalidation, a payload ``FrozenJson`` would
        never have accepted raises a raw serialisation error out of a method
        whose contract is that it answers a question — after the executor has
        already committed its ``→ RUNNING`` claim, leaving the step durably
        ``RUNNING`` until recovery. Revalidating first turns it into a rejection,
        and the ``ValidationError`` cause is the evidence of which ran.

        A suite mutating only into *valid* states passes under either order.
        """
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool())

        malformed = ActionRequest.model_construct(
            tool=call.request.tool,
            parameters={"to": {"a", "set", "has", "no", "json"}},
            step_id=call.request.step_id,
        )
        call.__dict__["request"] = malformed

        with pytest.raises(ToolBindingError) as caught:
            await invoked(invoker, trail, call, timeout=PATIENT)

        assert isinstance(caught.value.__cause__, ValidationError), (
            "a malformed mutation must be rejected by revalidation, not by the digest"
        )
        assert spy.calls == []

    # --- §4: the deadline -----------------------------------------------

    async def test_a_side_effecting_non_natural_tool_that_times_out_is_indeterminate(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0014 §4's case, reached through a deadline rather than a crash."""
        invoker.register(tool(), Slow())

        result = await invoked(invoker, trail, call_for(tool()), timeout=BRIEF)

        assert result.outcome is ToolOutcome.INDETERMINATE
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.TIMED_OUT
        assert result.output is None

    @pytest.mark.parametrize("definition", [read_only(), natural()], ids=["read-only", "natural"])
    async def test_a_read_only_or_natural_tool_that_times_out_is_failed(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail, definition: ToolDefinition
    ) -> None:
        """A read changed nothing; a ``NATURAL`` repeat does the same thing again."""
        invoker.register(definition, Slow())

        result = await invoked(invoker, trail, call_for(definition), timeout=BRIEF)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.TIMED_OUT

    @pytest.mark.parametrize(
        "bad",
        [timedelta(0), timedelta(seconds=-1), 5, None, "30s"],
        ids=["zero", "negative", "int", "none", "str"],
    )
    async def test_a_timeout_that_is_not_a_positive_timedelta_raises(
        self, invoker: InvocableToolRegistry, bad: object
    ) -> None:
        """Refused before the tool's coroutine is created.

        Not "expired means do not call": expiry is delivered at an await point,
        so a callable performing a synchronous side effect before its first
        ``await`` would already have acted. Refusing the value never creates the
        coroutine, which is the only placement that holds for every tool.
        """
        spy = Spy()
        invoker.register(tool(), spy)

        with pytest.raises(ValueError, match="timeout"):
            await invoker.invoke(call_for(tool()), timeout=bad)  # type: ignore[arg-type]  # the guard is the subject  # type: ignore[arg-type]
        assert spy.calls == []

    @pytest.mark.parametrize(
        "duration",
        ["raises", float("inf"), "not a number"],
        ids=["read-raises", "infinite", "non-numeric"],
    )
    async def test_a_timedelta_subclasss_overrides_never_decide_the_deadline(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry], duration: object
    ) -> None:
        """``isinstance`` admits a subclass, and the deadline is opened after the claim.

        A guard that validates the caller's object and hands the same object on
        accepts anything ``isinstance`` calls a ``timedelta``, and the seam then
        reads the duration *later* — opening ``asyncio.timeout`` after the claim
        has landed. A ``total_seconds`` that raises there escapes with a claim
        open, no completion written and no ``ToolResult`` at all, which is exactly
        the exit ADR-0192 §3 makes total over; one returning ``inf`` disables the
        deadline ADR-0029 §4 says there always is, in the one method whose
        contract is that there is one.

        So the duration is taken **before** the claim and from the base class's
        own fields, which a subclass cannot shadow. The three arms are three ways
        an override could decide something, and the assertion is the same in each:
        it decided nothing. The call runs normally, under its true 30 seconds,
        with the claim appended once and completed — no refusal invented, and no
        open row left behind.

        Refusing the value would also be a defensible design, and is a worse one:
        a plain ``timedelta`` is a valid deadline whatever a subclass says about
        it, and rejecting the whole subclass would make ``invoke`` refuse durations
        it can enforce exactly.
        """

        class Hostile(timedelta):
            """A real 30 seconds by every field, and a liar about all of them."""

            def total_seconds(self) -> float:
                if duration == "raises":
                    msg = "the duration refuses to be read"
                    raise RuntimeError(msg)
                return duration  # type: ignore[return-value]  # the guard is the subject

        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy(output={"unread": 2}))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        result = await invoker.invoke(call, timeout=Hostile(seconds=30))

        assert result.outcome is ToolOutcome.SUCCEEDED
        assert result.output == {"unread": 2}
        assert ledger.claim.calls == 1
        assert ledger.completion.calls == 1
        assert await trail.open_invocations(decision_id=call.decision.id) == [], (
            "the deadline is the base class's, so nothing raises after the claim"
        )

    async def test_a_timedelta_subclass_that_is_not_positive_is_still_refused(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """And the positivity check reads the snapshot, not the subclass.

        The companion to the case above: taking the duration from the base fields
        must not become a way *past* the guard. A subclass reporting itself
        positive through an overridden comparison is still zero, and is refused
        before the claim exactly as a plain ``timedelta(0)`` is.
        """

        class Optimistic(timedelta):
            """Claims to be longer than anything it is compared with."""

            def __le__(self, other: timedelta) -> bool:
                return False

        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        invoker = consuming(ledger)
        spy = Spy()
        invoker.register(read_only("inbox"), spy)
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        with pytest.raises(ValueError, match="timeout"):
            await invoker.invoke(call, timeout=Optimistic(0))

        assert spy.calls == [], "the callable is never entered"
        assert ledger.claim.calls == 0, "a refused deadline leaves no open invocation"

    async def test_a_tool_that_suppresses_its_cancellation_outlives_its_deadline(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The cooperative limit, deterministically (ADR-0029 §4).

        "Timeout" here means the seam stops waiting, not that the tool stops
        working — and no seam can make it stronger, because ``asyncio.timeout``
        does not return until the inner frame finishes unwinding. Pinning the
        limit is what stops an implementation quietly acquiring a watchdog.
        """
        stubborn = Stubborn()
        invoker.register(tool(), stubborn)

        running = asyncio.ensure_future(invoked(invoker, trail, call_for(tool()), timeout=BRIEF))
        await stubborn.entered.wait()
        await asyncio.sleep(BRIEF.total_seconds() * 5)

        assert not running.done(), "the deadline is not a hard bound, and must not look like one"

        stubborn.release.set()
        result = await running
        assert result.outcome is ToolOutcome.INDETERMINATE
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.TIMED_OUT

    # --- §3: an exception escaping the tool ------------------------------

    async def test_a_raising_tool_becomes_an_internal_result(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """Integration authors raise; a seam that let that propagate would leave
        the step durably ``RUNNING`` with nothing recording why.
        """
        invoker.register(tool(), Raiser(RuntimeError("upstream said no")))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        assert result.failure.kind.retryable is False

    async def test_a_tool_whose_exception_refuses_to_be_named_is_still_an_internal_result(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """ADR-0029 §3's rule has to survive the class the tool chose.

        A broken tool becomes a ``ToolResult``, not an exception — and the seam
        builds that result by naming the exception's class. The name is read from
        an object the *tool* controls: a metaclass may override the ``__name__``
        access and raise. Unguarded, that read escapes **after** the claim, so
        ``invoke`` raises the metaclass's exception, ADR-0192 §3 gets no
        completion for a claim it already appended, and a known-failed act
        permanently spends its authorisation with the failure lost as data.

        So the class is read once and totally, and where no name comes back the
        result carries ``core``'s own reserved literal — the same shape ADR-0192
        §3 gives a fault class that cannot be represented, rather than one
        invented for the position. The completion is written either way, which is
        the assertion that matters: the claim does not stay open.
        """

        class Unnameable(type):
            """Refuses to be named, with an ``Exception`` the guard catches."""

            def __getattribute__(cls, name: str) -> object:
                if name == "__name__":
                    msg = "the metaclass refuses to be named"
                    raise RuntimeError(msg)
                return super().__getattribute__(name)

        trail = FakeAuditTrail()
        invoker = consuming(trail)
        hostile = Unnameable("Hostile", (RuntimeError,), {})("upstream said no")
        invoker.register(read_only("inbox"), Raiser(hostile))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        result = await invoker.invoke(call, timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        assert result.failure.message == (
            f"{UNREPRESENTABLE_FAULT_CLASS} escaped tool {read_only('inbox').id!r}"
        )
        assert await trail.open_invocations(decision_id=call.decision.id) == [], (
            "the completion is written, so the claim does not stay open"
        )

    async def test_the_exceptions_own_text_never_reaches_the_failure_message(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The message-leak rule (§3), which nothing downstream would catch.

        ``core/logging.py`` redacts by *key* and names ``error=str(exc)`` as the
        Tier 1 leak it cannot see. ``message`` lands under precisely such a key,
        in a log and in ``StepExecution.error``, so the rule has to hold at the
        producer: a message the seam generates carries no content it did not
        author.
        """
        invoker.register(tool(), Raiser(RuntimeError("recipient alice@example.com rejected")))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.failure is not None
        assert "alice@example.com" not in result.failure.message
        assert "rejected" not in result.failure.message
        assert "RuntimeError" in result.failure.message

    @pytest.mark.parametrize("value", [{"a", "set"}, float("nan")], ids=["set", "nan"])
    async def test_a_return_value_frozen_json_refuses_becomes_internal(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail, value: object
    ) -> None:
        """A tool whose return value will not validate is broken, and saying so
        is more useful than storing something unserialisable — or than letting a
        ``ValidationError`` escape a method that returns classified data.
        """
        invoker.register(tool(), Returner(value))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL

    async def test_a_tools_own_timeout_error_inside_the_deadline_is_internal(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """``TIMED_OUT`` means *this* deadline expired, established not inferred.

        An upstream SDK raises Python's ``TimeoutError`` for its own reasons —
        a connect timeout, a read timeout it configures itself — often long
        inside our budget. Classifying by catching the type would label it
        ``TIMED_OUT`` and, for this side-effecting tool, escalate it to
        ``INDETERMINATE``: a call that failed fast and provably did nothing,
        recorded as one whose effect is unknown and therefore excluded from
        retry.
        """
        invoker.register(tool(), Raiser(TimeoutError("the upstream's own deadline")))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        assert result.outcome is ToolOutcome.FAILED

    async def test_a_base_exception_propagates_rather_than_becoming_a_result(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """A guard whose own failure modes bypass its failure path enforces nothing."""
        invoker.register(tool(), Raiser(KeyboardInterrupt()))

        with pytest.raises(KeyboardInterrupt):
            await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

    # --- §4: cancellation, classified by provenance ----------------------

    async def test_a_cancelled_error_the_tool_invents_is_an_internal_result(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """Nothing about the exception's type says where it came from.

        A tool raising one before it issues its request would otherwise read as
        an external teardown: the executor would record ``INDETERMINATE`` for a
        call that did nothing, and re-raise — cancelling a request nobody
        cancelled, on a tool's say-so. Paired with the next test, this is what
        pins the classification to provenance rather than to the type.
        """
        invoker.register(tool(), Raiser(asyncio.CancelledError()))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        task = asyncio.current_task()
        assert task is not None
        assert task.cancelling() == 0, "nothing was cancelled, so nothing may be left cancelling"

    @pytest.mark.parametrize(
        "definition", [tool(), read_only()], ids=["side-effecting", "read-only"]
    )
    async def test_an_external_cancellation_propagates_on_both_branches(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail, definition: ToolDefinition
    ) -> None:
        """The seam does not convert a real cancellation into a result.

        Swallowing it would break structured concurrency and shutdown, and there
        is no return path from a task being torn down. Committing the step by
        ADR-0029 §4's rule and then re-raising is the *executor's* obligation
        (§8), which is why what is pinned here is that the exception arrives
        rather than that a status was written.
        """
        slow = Slow()
        invoker.register(definition, slow)

        running = asyncio.ensure_future(
            invoked(invoker, trail, call_for(definition), timeout=PATIENT)
        )
        await slow.entered.wait()
        running.cancel()

        with pytest.raises(asyncio.CancelledError):
            await running

    async def test_a_tool_that_absorbs_its_deadline_is_not_reported_successful(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The deadline is read from the timeout, not inferred from an exception.

        A callable that catches the cancellation ``asyncio.timeout`` injects and
        returns a value leaves nothing to catch — so an implementation
        classifying only on what was raised hands back ``SUCCEEDED`` for a
        side-effecting call that ran past its deadline, which is the one
        direction ADR-0014 §4 refuses to guess in.
        """
        swallower = Swallower()
        invoker.register(tool(), swallower)

        result = await invoked(invoker, trail, call_for(tool()), timeout=BRIEF)

        assert swallower.swallowed, "the fixture must actually absorb the cancellation"
        assert result.outcome is ToolOutcome.INDETERMINATE
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.TIMED_OUT

    async def test_a_tool_that_absorbs_an_external_cancellation_still_cancels_the_call(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """A cancelled task must not be answered with a result.

        The cancellation was requested of the *invoking task*, and a callable
        catching it does not withdraw the request. Returning normally here would
        report a cancelled turn as ``SUCCEEDED`` and leave the executor with no
        cancellation to commit against or re-raise (ADR-0029 §4).
        """
        swallower = Swallower()
        invoker.register(tool(), swallower)

        running = asyncio.ensure_future(invoked(invoker, trail, call_for(tool()), timeout=PATIENT))
        await swallower.entered.wait()
        running.cancel()

        with pytest.raises(asyncio.CancelledError):
            await running
        assert swallower.swallowed

    @pytest.mark.parametrize(
        ("implementation", "expected"),
        [
            (Spy(), ToolOutcome.SUCCEEDED),
            (Raiser(asyncio.CancelledError()), ToolOutcome.FAILED),
        ],
        ids=["succeeds", "invents-a-cancellation"],
    )
    async def test_a_caller_that_absorbed_an_earlier_cancellation_is_not_treated_as_cancelled(
        self,
        invoker: InvocableToolRegistry,
        trail: FakeAuditTrail,
        implementation: FakeToolImplementation,
        expected: ToolOutcome,
    ) -> None:
        """Provenance is a delta, not a count.

        ``Task.cancelling()`` is a lifetime total that only ``uncancel()``
        lowers, so a caller that caught an earlier cancellation to finish some
        work still carries a positive count with nothing about *this* call
        cancelled. An implementation reading it as a boolean fails every
        subsequent invocation on that task, and turns a tool's invented
        ``CancelledError`` — which §4 requires to be ``INTERNAL`` — into a
        cancellation on the strength of something that predates the seam.
        """
        invoker.register(tool(), implementation)
        reached_the_sleep = asyncio.Event()

        async def caller() -> ToolOutcome:
            try:
                reached_the_sleep.set()
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                pass  # absorbed, and deliberately not `uncancel()`-ed
            result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)
            return result.outcome

        running = asyncio.ensure_future(caller())
        await reached_the_sleep.wait()
        running.cancel()

        assert await running is expected

    # --- §5: the key is the authorisation --------------------------------

    async def test_a_keyed_tool_receives_the_decision_id_as_its_key(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """Derived, not minted: there is no caller field to fill in wrongly."""
        spy = Spy()
        invoker.register(keyed(), spy)

        await invoked(invoker, trail, call_for(keyed(), decision_id="d-42"), timeout=PATIENT)

        assert [key for _, key in spy.calls] == ["d-42"]

    @pytest.mark.parametrize(
        "definition", [tool(), natural()], ids=["idempotency-none", "idempotency-natural"]
    )
    async def test_a_tool_that_is_not_keyed_receives_no_key(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail, definition: ToolDefinition
    ) -> None:
        """A key is meaningless to a tool that made no guarantee about one."""
        spy = Spy()
        invoker.register(definition, spy)

        await invoked(invoker, trail, call_for(definition), timeout=PATIENT)

        assert [key for _, key in spy.calls] == [None]

    async def test_the_key_is_identical_across_retries_of_one_call(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """There is deliberately no attempt counter: a key that varied per
        attempt would defeat the guarantee at exactly the moment it is needed.
        """
        spy = Spy()
        # Not spendable, so ADR-0192 §1 refuses no repetition and the *key* is
        # what this case is left testing — which is what it was always about.
        invoker.register(gated(), spy)
        call = call_for(gated(), decision_id="d-7")

        await invoked(invoker, trail, call, timeout=PATIENT)
        await invoked(invoker, trail, call, timeout=PATIENT)

        assert [key for _, key in spy.calls] == ["d-7", "d-7"]

    async def test_two_decisions_about_identical_parameters_derive_different_keys(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """A fresh authorisation is a fresh action, not a duplicate of the old one."""
        spy = Spy()
        invoker.register(keyed(), spy)
        payload = {"to": "someone@example.com"}

        await invoked(
            invoker,
            trail,
            call_for(keyed(), parameters=payload, decision_id="d-1"),
            timeout=PATIENT,
        )
        await invoked(
            invoker,
            trail,
            call_for(keyed(), parameters=payload, decision_id="d-2"),
            timeout=PATIENT,
        )

        assert [key for _, key in spy.calls] == ["d-1", "d-2"]

    async def test_the_key_is_reproducible_from_the_decision_alone_after_a_restart(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The property that makes the key worth anything.

        A restarted executor reads ``StepExecution.approval_ref``, loads *that*
        decision from the durable trail, rebuilds the request, and derives the
        identical key. A key held only in memory would be lost by precisely the
        crash it exists to survive — so this reloads the decision through a JSON
        round-trip rather than reusing the object.
        """
        spy = Spy()
        invoker.register(gated(), spy)
        before = call_for(gated(), decision_id="d-99")
        await invoked(invoker, trail, before, timeout=PATIENT)

        reloaded = PermissionDecision.model_validate(before.decision.model_dump(mode="json"))
        after = ToolCall(request=before.request, decision=reloaded)
        await invoked(invoker, trail, after, timeout=PATIENT)

        assert after.idempotency_key == before.idempotency_key
        assert [key for _, key in spy.calls] == ["d-99", "d-99"]

    async def test_a_keyed_tool_deduplicates_inside_its_window_and_acts_again_outside_it(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The tool's half of ADR-0029 §5's two-sided obligation.

        The executor's half — stopping once the window has elapsed, and treating
        any reading that is not a positive elapsed duration as *lapsed* — is an
        obligation on `orchestration`'s executor and is not observable here.
        """
        window = timedelta(hours=1)
        deduplicating = KeyedTool(window)
        # The non-spendable ``KEYED`` class: a repeat under one decision is what
        # this case is about, and ADR-0192 §1 admits one only here.
        invoker.register(gated(window=window), deduplicating)
        call = call_for(gated(window=window), decision_id="d-5")

        first = await invoked(invoker, trail, call, timeout=PATIENT)
        inside = await invoked(invoker, trail, call, timeout=PATIENT)
        deduplicating.now = AT + window + timedelta(seconds=1)
        outside = await invoked(invoker, trail, call, timeout=PATIENT)

        assert first.output == inside.output == 1
        assert outside.output == 2
        assert deduplicating.effects == 2

    # --- success ---------------------------------------------------------

    async def test_a_successful_call_returns_its_output_and_the_tools_arguments(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The happy path, and that the callable receives what was authorised."""
        spy = Spy(output={"message_id": "m-1"})
        invoker.register(tool(), spy)

        result = await invoked(
            invoker,
            trail,
            call_for(tool(), parameters={"to": "someone@example.com"}),
            timeout=PATIENT,
        )

        assert result.outcome is ToolOutcome.SUCCEEDED
        assert result.failure is None
        assert result.output == {"message_id": "m-1"}
        assert spy.calls == [({"to": "someone@example.com"}, None)]

    # --- ADR-0192 §1: the claim, and where it sits ------------------------

    async def test_a_call_claims_before_the_callable_and_completes_after(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The order ADR-0192 §1 places and §3 closes, asserted as a sequence.

        Held on a barrier the test owns, so "before" is observed rather than
        inferred from two rows that happen to be in that order: while the claim
        append is in flight the callable has **not** been entered and ``invoke``
        has not returned, and the completion exists only once the call has run.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.claim.hold = asyncio.Event()
        invoker = consuming(ledger)
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool())
        await trail.record(call.decision)

        task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
        await ledger.claim.entered.wait()

        assert spy.calls == [], "the claim is appended before the callable is entered"
        assert not task.done()
        assert await rows(trail) == []

        ledger.claim.hold.set()
        result = await task

        assert result.outcome is ToolOutcome.SUCCEEDED
        assert spy.calls == [({"to": "someone@example.com"}, None)]
        (claim,) = await claims(trail)
        (completion,) = await completions(trail)
        assert claim.decision_id == call.decision.id
        assert completion.completes == claim.id
        assert completion.outcome is ToolOutcome.SUCCEEDED
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    @pytest.mark.parametrize("refusal", ["unrecorded", "spent"])
    async def test_a_refused_claim_never_calls_the_registration(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry], refusal: str
    ) -> None:
        """ "Before the callable is entered" is about **calling**, not only awaiting.

        A registration is not required to be a native ``async def``, so obtaining
        its coroutine in order to hold one across the claim already runs whatever
        it does synchronously. An implementation that does so passes every case
        driven by an ``async def`` double and then performs a side effect under an
        authorisation the ledger went on to refuse — as spent, or as one the trail
        never recorded — which is the single thing ADR-0192 §1 exists to prevent.
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        factory = SynchronousFactory()
        invoker.register(tool(), factory)
        call = call_for(tool())

        if refusal == "spent":
            await trail.record(call.decision)
            await invoker.invoke(call, timeout=PATIENT)
            assert factory.entered == 1, "the first act reaches the registration"

        expected = AuthorisationSpentError if refusal == "spent" else UnrecordedAuthorisationError
        with pytest.raises(expected):
            await invoker.invoke(call, timeout=PATIENT)

        assert factory.entered == (1 if refusal == "spent" else 0), (
            "a refused claim calls the registration no further"
        )

    @pytest.mark.parametrize(
        "wiring",
        ["unbound-id", "substituted-definition", "unauthorised", "malformed-parameters"],
    )
    async def test_a_refused_check_appends_no_invocation_row(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry], wiring: str
    ) -> None:
        """Every check that raises a seam fault sits **above** the claim (ADR-0192 §1).

        Parameterised rather than written for one check, because a suite
        inspecting only the exception and the untouched callable certifies an
        implementation that claims first and then refuses — which enters no
        callable, raises the expected class, and has nonetheless spent the
        authorisation and left an open claim for a call that was never made.
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        spy = Spy()
        invoker.register(tool(), spy)

        call = call_for(tool("never-registered") if wiring == "unbound-id" else tool())
        await trail.record(call.decision)
        if wiring == "substituted-definition":
            object.__setattr__(call.request.tool, "risk_level", RiskLevel.LOW)
        elif wiring == "unauthorised":
            call.__dict__["request"] = ActionRequest(
                tool=tool(), parameters={"to": "elsewhere@example.com"}, step_id="step-1"
            )
        elif wiring == "malformed-parameters":
            call.__dict__["request"] = ActionRequest.model_construct(
                tool=call.request.tool,
                parameters={"to": {"a", "set", "has", "no", "json"}},
                step_id="step-1",
            )

        with pytest.raises(ToolBindingError):
            await invoker.invoke(call, timeout=PATIENT)

        assert spy.calls == [], "the callable was never reached"
        assert await rows(trail) == [], "a seam fault appends no invocation row"

    async def test_an_unrecorded_authorisation_is_refused_before_the_callable(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The claim is the consume, and a claim the ledger refuses never reaches the tool.

        The refusal reaches the caller **as its own class**, unwrapped: ADR-0192
        §2's exhaustive refusal orders would mean nothing if a caller could not
        catch the class they name (§1).
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        spy = Spy()
        invoker.register(tool(), spy)

        with pytest.raises(UnrecordedAuthorisationError):
            await invoker.invoke(call_for(tool()), timeout=PATIENT)

        assert spy.calls == []
        assert await rows(trail) == []

    async def test_a_second_act_under_a_spendable_authorisation_is_refused_at_the_seam(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """One authorisation, one act — and the refusal is what leaves ``invoke``.

        Asserted at the seam rather than on a ledger method driven directly: the
        refusal is ADR-0192 §1's and is decided inside the append, so a
        ledger-only test would pin the store's rule while leaving the seam free to
        swallow it.
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool())
        await trail.record(call.decision)

        first = await invoker.invoke(call, timeout=PATIENT)
        with pytest.raises(AuthorisationSpentError):
            await invoker.invoke(call, timeout=PATIENT)

        assert first.outcome is ToolOutcome.SUCCEEDED
        assert len(spy.calls) == 1, "the second act never reached the callable"
        assert len(await rows(trail)) == 2, "one claim and one completion, and no more"

    @pytest.mark.parametrize("definition", [read_only("inbox"), natural("upsert")])
    async def test_a_second_act_under_a_non_spendable_authorisation_is_admitted(
        self,
        consuming: Callable[[InvocationLedger], InvocableToolRegistry],
        definition: ToolDefinition,
    ) -> None:
        """A read gated by ADR-0016 §3 is invoked under one ``ALLOW`` as often as needed.

        The half a one-winner test cannot see: an implementation consuming every
        ``ALLOW`` would refuse the second gated read and the second ``NATURAL``
        invocation, which ADR-0192 §1 says are never refused on this ground.
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        spy = Spy()
        invoker.register(definition, spy)
        call = call_for(definition)
        await trail.record(call.decision)

        await invoker.invoke(call, timeout=PATIENT)
        await invoker.invoke(call, timeout=PATIENT)

        assert len(spy.calls) == 2
        assert len(await completions(trail)) == 2
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    async def test_a_completion_that_did_not_commit_leaves_the_claim_open_and_spends_it(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """Completion durability is a third prerequisite for a further act (ADR-0192 §1).

        The composition a suite holding the two halves separately cannot see: the
        completion append fails before committing, ``invoke`` returns the call's
        own result unchanged, and the next act under that authorisation is refused
        **twice over** — a claim is open, and the last claim in the append order is
        that same open one and so is not completed ``FAILED`` at all.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.error = RuntimeError("the store would not write")
        invoker = consuming(ledger)
        spy = Spy(output={"message_id": "m-1"})
        invoker.register(keyed(), spy)
        call = call_for(keyed())
        await trail.record(call.decision)

        result = await invoker.invoke(call, timeout=PATIENT)

        assert result.outcome is ToolOutcome.SUCCEEDED, "the act's own result stands"
        assert result.output == {"message_id": "m-1"}
        assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1
        assert await completions(trail) == []

        with pytest.raises(AuthorisationSpentError):
            await invoker.invoke(call, timeout=PATIENT)

        assert len(spy.calls) == 1, "no second callable was entered"
        assert len(await rows(trail)) == 1, "one claim, still open, and no completion"

    # --- ADR-0192 §2, §5: what the completion row carries ------------------

    async def test_a_success_completes_with_no_kind_and_a_cost_nobody_measured(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The declaration's price appears on no row, on this path or any other.

        ``ToolResult.incurred_cost`` is what the *tool* reported, and nothing
        populates it yet (#1558), so the row records an ``UNKNOWN`` basis. A lane
        filling it from ``ToolDefinition.cost`` would put a declaration where a
        measurement belongs and corrupt the spend total ADR-0192 §5 is built on.
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        priced = tool(
            cost=ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.01"), currency="USD")
        )
        invoker.register(priced, Spy())
        call = call_for(priced)
        await trail.record(call.decision)

        await invoker.invoke(call, timeout=PATIENT)

        (completion,) = await completions(trail)
        assert completion.outcome is ToolOutcome.SUCCEEDED
        assert completion.failure_kind is None, (
            "a SUCCEEDED result carries no failure to transcribe"
        )
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)

    @pytest.mark.parametrize(
        ("definition", "expected"),
        [(read_only("inbox"), ToolOutcome.FAILED), (keyed(), ToolOutcome.INDETERMINATE)],
    )
    async def test_a_deadline_transcribes_its_kind_onto_the_completion(
        self,
        consuming: Callable[[InvocationLedger], InvocableToolRegistry],
        definition: ToolDefinition,
        expected: ToolOutcome,
    ) -> None:
        """``TIMED_OUT`` is transcribed and never dropped, on both outcomes.

        A ``FAILED``-with-kind case is owed separately from the
        ``INDETERMINATE``-with-kind one: an implementation can preserve one and
        drop the other, and dropping either produces a valid kindless completion
        that silently refuses a legitimate retry as spent (ADR-0192 §9).
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        invoker.register(definition, Slow())
        call = call_for(definition)
        await trail.record(call.decision)

        result = await invoker.invoke(call, timeout=BRIEF)

        assert result.outcome is expected
        (completion,) = await completions(trail)
        assert completion.outcome is expected
        assert completion.failure_kind is ToolFailureKind.TIMED_OUT
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)

    @pytest.mark.parametrize(
        ("definition", "expected"),
        [(read_only("inbox"), ToolOutcome.FAILED), (tool(), ToolOutcome.INDETERMINATE)],
    )
    async def test_a_cancelled_call_completes_kindless_at_an_unknown_cost(
        self,
        consuming: Callable[[InvocationLedger], InvocableToolRegistry],
        definition: ToolDefinition,
        expected: ToolOutcome,
    ) -> None:
        """A completion derived from no ``ToolResult`` invents neither field.

        ``failure_kind`` is transcribed and never synthesised — ADR-0031 §3 rules
        that the seam never synthesises ``CANCELLED`` — and the cost is the
        ``UNKNOWN`` basis, never the declaration's figure. Without this a spend
        accumulator counts an invented measurement.
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        slow = Slow()
        invoker.register(definition, slow)
        call = call_for(definition)
        await trail.record(call.decision)

        task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
        await slow.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        (completion,) = await completions(trail)
        assert completion.outcome is expected
        assert completion.failure_kind is None
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    # --- ADR-0192 §3: a failed append changes nothing about the act --------

    async def test_a_completion_that_fails_does_not_change_what_the_call_returned(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """A ``SUCCEEDED`` side effect is not reported as failed because a disk was full.

        The failure is not swallowed either: it reaches the operator as a Tier 2
        diagnostic carrying the operation, the fault class and the outcome that
        was being written — and **nothing else**, the instance, the message and
        every member of the cause chain included (ADR-0192 §3, ADR-0004 §5).
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.error = RuntimeError("recipient@example.com")
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy(output={"unread": 3}))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            result = await invoker.invoke(call, timeout=PATIENT)

        assert result.outcome is ToolOutcome.SUCCEEDED
        assert result.output == {"unread": 3}
        assert appended(captured) == [
            {
                "operation": COMPLETION,
                "fault_class": "RuntimeError",
                "outcome": ToolOutcome.SUCCEEDED,
            }
        ]
        assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1

    async def test_the_diagnostics_four_shapes_carry_exactly_their_own_fields(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """ADR-0192 §3's matrix, shape by shape, with absent fields asserted absent.

        A shape-by-shape test is owed because every drift this rule has had was a
        clause restating the field list for one case and disagreeing with another.
        The claim shapes carry **no** outcome — a claim carries no ``ToolOutcome``
        at all, so nothing stands in for it and no literal is minted for the
        position — and the ``BaseException`` shapes carry **no class**, which is
        ``fault_class_of``'s own rule read forward rather than worked around.
        """
        shapes: list[tuple[str, BaseException, dict[str, object]]] = [
            ("claim", RuntimeError("boom"), {"operation": CLAIM, "fault_class": "RuntimeError"}),
            ("claim", KeyboardInterrupt(), {"operation": CLAIM}),
            (
                "completion",
                RuntimeError("boom"),
                {
                    "operation": COMPLETION,
                    "fault_class": "RuntimeError",
                    "outcome": ToolOutcome.SUCCEEDED,
                },
            ),
            (
                "completion",
                KeyboardInterrupt(),
                {"operation": COMPLETION, "outcome": ToolOutcome.SUCCEEDED},
            ),
        ]
        for member, error, expected in shapes:
            trail = FakeAuditTrail()
            ledger = DrivenLedger(trail)
            getattr(ledger, member).error = error
            invoker = consuming(ledger)
            invoker.register(read_only("inbox"), Spy())
            call = call_for(read_only("inbox"))
            await trail.record(call.decision)

            # The exit itself is the other cases' subject; this one is about the
            # fields the diagnostic carries on the way out.
            with structlog.testing.capture_logs() as captured, contextlib.suppress(BaseException):
                await invoker.invoke(call, timeout=PATIENT)

            assert appended(captured) == [expected], f"{member} raising {type(error).__name__}"

    async def test_no_tier_one_content_reaches_the_diagnostic_by_any_route(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The sentinel in four hostile positions (ADR-0192 §9, ADR-0004 §5).

        A message, a member of the cause chain, an identifier, and the **class
        name** of a dynamically built exception. On the first three the assertion
        is that no such name reaches the log at all; on the fourth it is
        ``fault_class_of``'s own boundary and nothing wider — a name outside that
        function's identifier pattern becomes the reserved literal, and the
        residue for a *pattern-valid* hostile name is ADR-0119's, filed as #1569.
        """
        sentinel = "recipient@example.com"
        hostile = type(sentinel, (RuntimeError,), {})
        error = hostile("the message names " + sentinel)
        error.__cause__ = ValueError("the cause names " + sentinel)

        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.error = error
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy())
        call = call_for(read_only("inbox"), decision_id=sentinel)
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            await invoker.invoke(call, timeout=PATIENT)

        (diagnostic,) = appended(captured)
        assert diagnostic == {
            "operation": COMPLETION,
            "fault_class": UNREPRESENTABLE_FAULT_CLASS,
            "outcome": ToolOutcome.SUCCEEDED,
        }
        assert sentinel not in repr(captured), "no route carries a Tier 1 name into the log"

    async def test_a_class_name_that_cannot_be_read_becomes_the_reserved_literal(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """``fault_class_of``'s totality is what ADR-0192 §3 relies on, so it is pinned.

        The suite already covers a name outside the identifier pattern; this is
        the other arm — an exception whose ``__name__`` **access** raises an
        ``Exception``. It yields the same reserved literal, and it neither takes
        the diagnostic down nor changes what ``invoke`` returns. An implementation
        that validated ordinary names but let that access failure escape would
        replace a successful call's result with a bookkeeping failure, which is
        the one outcome §3 calls worse than an incomplete record.

        **No case asserts a literal where the ``__name__`` read raises a
        ``BaseException`` that is not an ``Exception``**, and none may:
        ``fault_class_of`` lets that one propagate by design, so a test demanding
        the literal would demand the widening ADR-0119 refuses (ADR-0192 §9).
        """
        unnameable = NameRaises("Unnameable", (RuntimeError,), {})
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.error = unnameable("the store would not write")
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy(output={"unread": 7}))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            result = await invoker.invoke(call, timeout=PATIENT)

        assert result.output == {"unread": 7}, "the diagnostic never changes what invoke returns"
        assert appended(captured) == [
            {
                "operation": COMPLETION,
                "fault_class": UNREPRESENTABLE_FAULT_CLASS,
                "outcome": ToolOutcome.SUCCEEDED,
            }
        ]

    async def test_a_collaborators_cancellation_on_the_completion_path_is_absorbed(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """A cancellation with nothing cancelled is not a cancellation of this call.

        Propagating it would discard a ``ToolResult`` the tool had already
        produced and hand the executor a ``CancelledError`` for a call nothing
        cancelled — a known-successful side effect recorded as interrupted, the
        one outcome ADR-0192 §3 calls worse than an incomplete record. The two
        cases are told apart by the ``Task.cancelling()`` count and by nothing
        else, so the diagnostic carries no class.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.error = asyncio.CancelledError("the ledger invented one")
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy(output={"unread": 1}))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            result = await invoker.invoke(call, timeout=PATIENT)

        assert result.output == {"unread": 1}
        assert appended(captured) == [{"operation": COMPLETION, "outcome": ToolOutcome.SUCCEEDED}]
        assert ledger.completion.calls == 1, "no exit attempts a second completion for one claim"
        assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1

    async def test_a_collaborators_cancellation_on_the_claim_path_is_an_audit_error(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The mirror case at the seam, and it must **not** leave as a ``CancelledError``.

        No callable was entered and no claim was observed, so this is a
        pre-callable exit: ADR-0034 §1's second ground classifies the step
        ``FAILED`` and no retry follows. Leaving as a cancellation would have the
        executor record ``interrupted_outcome`` — ``INDETERMINATE`` for a
        side-effecting tool — for a call that provably did not run.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        invented = asyncio.CancelledError("the ledger invented one")
        ledger.claim.error = invented
        invoker = consuming(ledger)
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool())
        await trail.record(call.decision)

        with pytest.raises(AuditError) as caught:
            await invoker.invoke(call, timeout=PATIENT)

        assert not isinstance(caught.value, asyncio.CancelledError)
        assert caught.value.__cause__ is invented
        assert spy.calls == []
        assert await rows(trail) == []

    async def test_a_collaborators_cancellation_on_the_claim_path_propagates_when_one_is_pending(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The other side of the discriminator, on the path the mirror case owns.

        Told apart by the ``Task.cancelling()`` **count** and by nothing else —
        never by the exception's class, never by its identity, and never by where
        in the body it surfaced (ADR-0192 §1, §3). With the count **increased** a
        cancellation request really did reach this task, so the ``CancelledError``
        is what leaves and ADR-0029 §4's classification of a genuinely cancelled
        call is untouched. An implementation that always translated a claim-side
        collaborator cancellation to ``AuditError`` would pass the unmoved-count
        case beside this one and lose a real concurrent shutdown.

        The executor's half of this pair — that it commits ``interrupted_outcome``
        here and ``FAILED`` on the unmoved-count case — is `orchestration`'s and
        is owed by the group that owns the executor (ADR-0192 §9).
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.claim.hold = asyncio.Event()
        invented = asyncio.CancelledError("the ledger invented one")
        ledger.claim.error = invented
        invoker = consuming(ledger)
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool())
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
            await ledger.claim.entered.wait()
            task.cancel()
            await _settled()
            ledger.claim.hold.set()
            with pytest.raises(asyncio.CancelledError) as caught:
                await task

        assert not isinstance(caught.value, AuditError)
        assert caught.value.__cause__ is invented
        assert task.cancelled()
        assert spy.calls == [], "the callable is never entered"
        assert ledger.completion.calls == 0
        assert appended(captured) == [{"operation": CLAIM}], "a cancellation is not a fault class"

    @pytest.mark.parametrize("member", ["claim", "completion"])
    async def test_a_class_name_read_that_raises_a_base_exception_is_not_absorbed(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry], member: str
    ) -> None:
        """``fault_class_of``'s guard stops at ``Exception``, and §3 does not widen it.

        A metaclass whose ``__name__`` access raises a ``BaseException`` that is not
        an ``Exception`` leaves the classifier by design, and ADR-0192 §3 gives it
        no exemption: it "is governed by this section's own clauses on a
        ``BaseException`` raised there … everything else propagating unchanged with
        **no diagnostic standing in for it**". So it is **not** swallowed behind the
        append's own failure — the call does not return a ``ToolResult``, and the
        claim path does not answer with the ``AuditError`` it would give an
        ordinary ``Exception``.

        **And no diagnostic is written at all.** §3 says of that exception that "it
        leaves the emitting frame", which is false of an implementation that
        catches it inside the emitter, omits the class field and writes the record
        anyway — and that record is exactly the one standing in for the exception
        §3 forbids. An earlier draft of this suite asserted the omitted-field
        shape here; it was asserting the construct the clause rules out. The
        omitted-field shape is still right where the *append's own* failure is a
        ``BaseException`` no class can be read from — that case is next — and the
        two are told apart by which exception the classifier was asked about.

        The class that leaves is not asserted: on the completion path this runs
        inside a retained append, which is the one thing §3 declines to state.
        """

        # A single instance, so the case can assert **identity** rather than class:
        # ADR-0192 §3 requires this exception to propagate *unchanged*, and an
        # implementation that annotates it on the way — attaching the append's
        # failure as its context, say — hands the caller whatever a hostile
        # ``__setattr__`` raises instead of the exception itself.
        interrupt = KeyboardInterrupt("the metaclass refuses to be named")

        class Unnameable(type):
            """Refuses to be named, with a ``BaseException`` the guard lets pass."""

            def __getattribute__(cls, name: str) -> object:
                if name == "__name__":
                    raise interrupt
                return super().__getattribute__(name)

        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        getattr(ledger, member).error = Unnameable("Hostile", (RuntimeError,), {})("boom")
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy(output={"unread": 1}))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        returned: ToolResult | None = None
        raised: BaseException | None = None
        with structlog.testing.capture_logs() as captured:
            try:
                returned = await invoker.invoke(call, timeout=PATIENT)
            except BaseException as exc:
                raised = exc

        assert raised is interrupt, (
            "the classifier's own failure propagates unchanged — neither absorbed, "
            "nor translated, nor replaced by the failure of annotating it"
        )
        assert returned is None
        assert appended(captured) == [], (
            "the exception leaves the emitting frame, so no diagnostic stands in for it"
        )

    async def test_a_raising_log_processor_costs_the_diagnostic_and_nothing_else(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """A broken *emitter* is not the classifier ADR-0192 §3 governs.

        §3's subject throughout is what may be **read off an exception and
        rendered** — the fault class, the field omitted where none can be read,
        the ``BaseException`` the name read raises and the clauses that dispose of
        it. It says nothing at all about the pipeline the rendered fields are then
        handed to, and ADR-0004 §5 and ADR-0119 likewise govern what a diagnostic
        may *carry* rather than what happens when the sink behind it is
        misconfigured. So the guard this case requires around the **emission** is
        not the guard §3 puts on the **classify**; the two are separable because
        they are about different things.

        **What an unguarded emitter costs.** Since the classifier's own failure is
        routed to the append path for disposition (§3), an exception the *emitter*
        raises would be routed there too — and would then stand in for the append
        failure it was being emitted about. On the claim path the caller is told
        the claim failed because a log sink did: an ``AuditError`` whose cause is
        the sink's exception, with the ledger's own failure nowhere in the chain.
        On the completion path it is absorbed in that failure's place, so a
        propagating cancellation carries the sink's exception as its cause instead
        of the append's. Neither is a fault of the *call*, and reporting a
        completed act as failed because a disk was full is precisely what §3 calls
        worse than an incomplete record — the fail-open ADR-0034 §1 exists to
        prevent.

        So an ``Exception`` from the pipeline costs the **diagnostic** and nothing
        else: the append's own failure stays intact for the path to dispose of by
        its own rules, and a successful ``ToolResult`` still reaches the caller.

        The processor is configured rather than the module logger patched, because
        a shared suite has two subjects in two modules and only the pipeline is
        common to both. ``capture_logs`` cannot serve here at all — it *replaces*
        the chain, which is the thing under test.
        """

        class BrokenSinkError(Exception):
            """What a misconfigured processor raises on the way to its sink."""

        def refuse(_logger: object, _name: str, _event: MutableMapping[str, Any]) -> NoReturn:
            msg = "the log pipeline is broken"
            raise BrokenSinkError(msg)

        async def under_a_broken_sink(
            member: str, error: Exception
        ) -> tuple[FakeAuditTrail, ToolResult | None, BaseException | None]:
            trail = FakeAuditTrail()
            ledger = DrivenLedger(trail)
            getattr(ledger, member).error = error
            invoker = consuming(ledger)
            invoker.register(read_only("inbox"), Spy(output={"unread": 3}))
            call = call_for(read_only("inbox"))
            await trail.record(call.decision)

            configured = structlog.get_config()
            structlog.configure(processors=[refuse])
            try:
                return trail, await invoker.invoke(call, timeout=PATIENT), None
            except BaseException as exc:  # the case below decides what it means
                return trail, None, exc
            finally:
                structlog.configure(**configured)

        # The claim path reports a fault, and the fault it reports is the ledger's.
        refused = RuntimeError("the store would not write the claim")
        _, returned, raised = await under_a_broken_sink("claim", refused)
        assert returned is None
        assert isinstance(raised, AuditError)
        assert raised.__cause__ is refused, (
            "the diagnostic's own failure never stands in for the append failure "
            "the operator is being told about"
        )

        # The completion path returns the result the tool already produced.
        trail, returned, raised = await under_a_broken_sink(
            "completion", RuntimeError("the store would not write the completion")
        )
        assert raised is None
        assert returned is not None
        assert returned.outcome is ToolOutcome.SUCCEEDED
        assert returned.output == {"unread": 3}, "a broken log sink does not fail a completed act"
        open_after = await trail.open_invocations(
            decision_id=call_for(read_only("inbox")).decision.id
        )
        assert len(open_after) == 1, "the completion was refused, so the claim is left open"

        # And the same holds of the *tool-failure* diagnostic, which runs after
        # the claim: a broken sink there would leave this frame in place of the
        # `ToolResult`, so §3 would get no completion for a claim already
        # appended — a known-failed act permanently spending its authorisation,
        # with the tool's failure lost as data (ADR-0029 §3).
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        invoker.register(read_only("inbox"), Raiser(RuntimeError("upstream said no")))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        configured = structlog.get_config()
        structlog.configure(processors=[refuse])
        try:
            failed = await invoker.invoke(call, timeout=PATIENT)
        finally:
            structlog.configure(**configured)

        assert failed.outcome is ToolOutcome.FAILED
        assert failed.failure is not None
        assert failed.failure.kind is ToolFailureKind.INTERNAL
        assert await trail.open_invocations(decision_id=call.decision.id) == [], (
            "the completion is written, so the claim does not stay open"
        )

    @pytest.mark.parametrize("member", ["claim", "completion"])
    async def test_a_non_assistant_error_reaches_the_caller_as_an_audit_error_or_is_absorbed(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry], member: str
    ) -> None:
        """The two boundaries answer differently, and an earlier draft ran them together.

        On the **claim** path an exception that is not an ``AssistantError`` is
        translated to an ``AuditError`` carrying it as the cause, its type intact
        — parameterised over three classes, so an implementation that catches one
        name rather than the class boundary fails. On the **completion** path none
        leaves at all, because it is absorbed (ADR-0192 §1, §3).
        """

        class BespokeError(Exception):
            """An exception class this test defines, so no name is being caught."""

        for raised in (RuntimeError("a"), ValueError("b"), BespokeError("c")):
            trail = FakeAuditTrail()
            ledger = DrivenLedger(trail)
            getattr(ledger, member).error = raised
            invoker = consuming(ledger)
            invoker.register(read_only("inbox"), Spy())
            call = call_for(read_only("inbox"))
            await trail.record(call.decision)

            if member == "claim":
                with pytest.raises(AuditError) as caught:
                    await invoker.invoke(call, timeout=PATIENT)
                assert caught.value.__cause__ is raised
            else:
                result = await invoker.invoke(call, timeout=PATIENT)
                assert result.outcome is ToolOutcome.SUCCEEDED

    async def test_a_base_exception_on_the_completion_path_is_not_absorbed(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """A process being torn down is not a refusal (ADR-0192 §3).

        No ``ToolResult`` reaches the caller, no completion is written, the claim
        is left open and the diagnostic carries **no class**. The test asserts
        those and stops there, asserting **nothing** about the class ``invoke``
        raises outward: that clock runs inside a retained append, and ADR-0192 §3
        leaves exactly that one thing uncontracted, so a case asserting it would
        pin behaviour the ADR declines to state.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.error = KeyboardInterrupt()
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy(output={"unread": 1}))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        returned: ToolResult | None = None
        raised: BaseException | None = None
        with structlog.testing.capture_logs() as captured:
            try:
                returned = await invoker.invoke(call, timeout=PATIENT)
            except BaseException as exc:
                # Captured rather than named: ADR-0192 §3 leaves the outward class
                # of a `BaseException` raised inside a retained append
                # uncontracted, so nothing here asserts one. That it *left* is a
                # different claim and is asserted — absorbing a `KeyboardInterrupt`
                # into a returned `None` would pass a suppression alone.
                raised = exc

        assert raised is not None, "a torn-down process is not absorbed"
        assert returned is None, "no result is manufactured for one"
        assert appended(captured) == [{"operation": COMPLETION, "outcome": ToolOutcome.SUCCEEDED}]
        assert await completions(trail) == []
        assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1

    async def test_a_base_exception_from_the_callable_propagates_unchanged(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The path that **is** contracted, and it answers differently (ADR-0192 §3).

        The callable is awaited **directly** and is not isolated in a task, so its
        own ``KeyboardInterrupt`` propagates unchanged, asserted by class. A suite
        omitting this would admit an implementation that had isolated the callable
        too — the shape ADR-0031 §4 refused outright.
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        invoker.register(tool(), Raiser(KeyboardInterrupt()))
        call = call_for(tool())
        await trail.record(call.decision)

        with pytest.raises(KeyboardInterrupt):
            await invoker.invoke(call, timeout=PATIENT)

        assert await completions(trail) == [], "no outcome is invented for one"
        assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1

    # --- ADR-0192 §1, §3: what the store already committed, stands ---------

    async def test_a_claim_that_committed_and_then_raised_leaves_its_row_standing(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """No rollback is on offer, and none is faked (ADR-0192 §1, §6).

        The row is durable before the failure reaches the frame. ``invoke``
        observed no claim, so it enters no callable and attempts no completion —
        and the committed row **stands**: nothing deleted, no compensating append,
        no marker. Without this case a suite certifies an implementation that
        cleans up after itself.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.claim.error = RuntimeError("the connection dropped after the commit")
        ledger.claim.commits = True
        invoker = consuming(ledger)
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool())
        await trail.record(call.decision)

        with pytest.raises(AuditError):
            await invoker.invoke(call, timeout=PATIENT)

        assert spy.calls == [], "the callable is never entered"
        assert ledger.completion.calls == 0, "no completion is attempted for a claim never observed"
        assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1

    async def test_a_completion_that_committed_and_then_raised_leaves_the_claim_closed(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The other side of the commit-state split, on the same clause.

        A suite carrying only the failed-before-commit timing certifies an
        implementation that tries to repair this one. What ``invoke`` returns is
        decided independently of which side of the commit the failure landed on,
        and the test asserts that too.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.error = RuntimeError("the connection dropped after the commit")
        ledger.completion.commits = True
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy(output={"unread": 2}))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        result = await invoker.invoke(call, timeout=PATIENT)

        assert result.output == {"unread": 2}, "the outward answer is decided independently"
        (completion,) = await completions(trail)
        assert completion.outcome is ToolOutcome.SUCCEEDED
        assert await trail.open_invocations(decision_id=call.decision.id) == []
        assert ledger.completion.calls == 1, "no compensating append and no second completion"

    @pytest.mark.parametrize("timing", ["before-the-commit", "after-the-commit"])
    @pytest.mark.parametrize(
        "branch",
        [
            "absorbed-exception",
            "invented-cancellation",
            "torn-down",
            "external-cancellation",
            "external-cancellation-meeting-an-invented-one",
        ],
    )
    async def test_the_commit_state_split_holds_on_every_completion_failure_branch(
        self,
        consuming: Callable[[InvocationLedger], InvocableToolRegistry],
        branch: str,
        timing: str,
    ) -> None:
        """What the store already committed, stands — on **every** failure branch.

        An implementation may honour the commit-state rule on one path and repair
        the others, so each branch is driven with the append failing **before** it
        commits, where the claim is left open, and again with the row durable
        before the failure reaches the frame, where the completion stands and the
        claim it names is closed. Nothing is deleted, rewritten or compensated to
        make the two look alike: ADR-0192 §6 offers no selective delete, and
        ADR-0060 §1 already rules that an abandoned append may have committed.

        **What ``invoke`` returns or raises is decided independently of which side
        of the commit the failure landed on**, and the test asserts that too —
        which is exactly what a repairing implementation gets wrong.
        """
        errors: dict[str, BaseException] = {
            "absorbed-exception": RuntimeError("the store would not write"),
            "invented-cancellation": asyncio.CancelledError("the ledger invented one"),
            "torn-down": KeyboardInterrupt(),
            "external-cancellation": RuntimeError("the store would not write"),
            # The discriminator's other side: a collaborator's `CancelledError`
            # while an external one **is** propagating is not absorbed. An
            # implementation that always absorbs a completion-path cancellation
            # would lose a real concurrent shutdown (ADR-0192 §3, ADR-0060 §1).
            "external-cancellation-meeting-an-invented-one": asyncio.CancelledError(
                "the ledger invented one"
            ),
        }
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.error = errors[branch]
        ledger.completion.commits = timing == "after-the-commit"
        invoker = consuming(ledger)
        cancelled = branch.startswith("external-cancellation")
        implementation = Slow() if cancelled else Spy(output={"unread": 1})
        invoker.register(read_only("inbox"), implementation)
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        returned: ToolResult | None = None
        raised: BaseException | None = None
        try:
            if cancelled:
                # A task only where one is needed: a `BaseException` propagating
                # out of a task is re-raised into the event loop (ADR-0031 §4), so
                # the torn-down branch is awaited in this frame instead.
                task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
                await implementation.entered.wait()  # type: ignore[union-attr]  # `Slow` here
                task.cancel()
                returned = await task
            else:
                returned = await invoker.invoke(call, timeout=PATIENT)
        except BaseException as exc:
            # Every class: which one leaves is the branch's own subject, asserted
            # below rather than narrowed by the `raises` that catches it.
            raised = exc

        if branch in {"absorbed-exception", "invented-cancellation"}:
            assert returned is not None
            assert returned.output == {"unread": 1}, "the act's own result stands"
        elif branch == "torn-down":
            assert returned is None, "no result is manufactured for a torn-down process"
        else:
            assert isinstance(raised, asyncio.CancelledError)
            assert raised.__cause__ is errors[branch]

        assert ledger.completion.calls == 1, "no second completion is attempted for one claim"
        if timing == "after-the-commit":
            assert len(await completions(trail)) == 1, "the committed row stands"
            assert await trail.open_invocations(decision_id=call.decision.id) == []
        else:
            assert await completions(trail) == []
            assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1

    async def test_an_erasure_between_the_claim_and_its_completion_leaves_no_claim(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """``clear()`` wins over a write in flight (ADR-0192 §3, §6).

        The call's own result stands, the refusal reaches the operator as a
        diagnostic, and **nothing is recreated**: the "claim left open"
        postcondition is not an obligation to put back a row the user destroyed on
        purpose, which §6 names as the one answer no store may give.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.hold = asyncio.Event()
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy(output={"unread": 4}))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
            await ledger.completion.entered.wait()
            await trail.clear()
            ledger.completion.hold.set()
            result = await task

        assert result.output == {"unread": 4}
        assert appended(captured) == [
            {
                "operation": COMPLETION,
                "fault_class": "InvalidCompletionError",
                "outcome": ToolOutcome.SUCCEEDED,
            }
        ]
        assert await rows(trail) == [], "nothing is recreated over an erased claim"

    # --- ADR-0192 §1, §3: neither append is bounded, and both are shielded --

    async def test_neither_append_is_bounded_by_the_seams_deadline(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """A lane that "helpfully" wraps either in a deadline breaks a clause here.

        ``invoke`` is given a ``timeout`` far shorter than each barrier is held
        for, and the **negative** is what is asserted while the barrier is held:
        no return, no ``AuditError``, no diagnostic, no ``ToolResult``. Nothing
        advances the ledger's clock, because that clock supplies instants and
        nothing here is decided on a duration at all — the determinism comes from
        the ordering the barrier fixes.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.claim.hold = asyncio.Event()
        invoker = consuming(ledger)
        spy = Spy()
        invoker.register(read_only("inbox"), spy)
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        held = asyncio.create_task(invoker.invoke(call, timeout=BRIEF))
        await ledger.claim.entered.wait()
        await _settled()

        assert not held.done(), "the claim append outlasts the call's deadline"
        assert spy.calls == []

        ledger.claim.hold.set()
        ledger.completion.hold = asyncio.Event()
        await ledger.completion.entered.wait()
        await _settled()

        assert not held.done(), "the completion append outlasts it too"
        assert len(spy.calls) == 1, "the callable has run and its result is computed"

        ledger.completion.hold.set()
        result = await held

        assert result.outcome is ToolOutcome.SUCCEEDED
        assert len(await completions(trail)) == 1

    async def test_two_cancellations_during_the_claim_append_do_not_lose_the_claim(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The shield, and ADR-0192 §1's clause on a cancellation before the callable.

        One cancellation is passed by an implementation that shields the first
        await and then awaits the retained task bare, so two are delivered and the
        test asserts ``invoke`` was still waiting after the second. Four things
        follow once the append lands: the callable is **never entered**; the
        completion carrying what ADR-0029 §4 computes for that cancellation is
        **durably appended**; **no claim is left open**; and the
        ``CancelledError`` still reaches the caller, with the task ending
        cancelled (ADR-0060 §1).
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.claim.hold = asyncio.Event()
        invoker = consuming(ledger)
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool())
        await trail.record(call.decision)

        task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
        await ledger.claim.entered.wait()
        for _ in range(2):
            task.cancel()
            await _settled()
            assert not task.done(), "absorbing exactly one cancellation is a failure"

        ledger.claim.hold.set()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert task.cancelled()
        assert spy.calls == [], "the callable is never entered"
        (completion,) = await completions(trail)
        assert completion.outcome is ToolOutcome.INDETERMINATE
        assert completion.failure_kind is None
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    async def test_a_cancellation_during_a_failing_claim_carries_its_failure_out(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The **append-fails** twin of the append-lands case, and the exits differ.

        There the append succeeded, so a completion is owed and its absence is the
        defect. Here ``invoke`` observed **no** claim, so it enters no callable and
        completes nothing — and the cancellation is delivered onward **whatever
        the append did** (ADR-0060 §1): the append's failure does not stand in its
        place, it is attached as the cause and reaches the operator through the
        diagnostic. An implementation can pass either case and fail the other.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.claim.hold = asyncio.Event()
        failure = RuntimeError("the store would not write")
        ledger.claim.error = failure
        invoker = consuming(ledger)
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool())
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
            await ledger.claim.entered.wait()
            task.cancel()
            await _settled()
            ledger.claim.hold.set()
            with pytest.raises(asyncio.CancelledError) as caught:
                await task

        assert caught.value.__cause__ is failure, "the append failure never stands in its place"
        assert task.cancelled()
        assert spy.calls == [], "the callable is never entered"
        assert ledger.completion.calls == 0, "no completion is attempted for a claim never observed"
        assert appended(captured) == [{"operation": CLAIM, "fault_class": "RuntimeError"}]

    async def test_two_cancellations_during_a_failing_completion_carry_its_failure_out(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The shield on the *second* append, which §3 puts on each and not the first.

        An implementation can shield the claim robustly and then await the
        retained completion task bare, losing the append's real failure to the
        cancellation ADR-0054 permits the store to re-raise in its place — and
        reporting neither the fault nor the open claim. Here the cancellation is
        what leaves, carrying the append's failure as its ``__cause__``, the
        diagnostic is emitted, and the claim is left open.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.hold = asyncio.Event()
        failure = RuntimeError("the worker failed")
        ledger.completion.error = failure
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy())
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
            await ledger.completion.entered.wait()
            for _ in range(2):
                task.cancel()
                await _settled()
                assert not task.done(), "absorbing exactly one cancellation is a failure"

            ledger.completion.hold.set()
            with pytest.raises(asyncio.CancelledError) as caught:
                await task

        assert caught.value.__cause__ is failure
        assert task.cancelled()
        assert appended(captured) == [
            {
                "operation": COMPLETION,
                "fault_class": "RuntimeError",
                "outcome": ToolOutcome.SUCCEEDED,
            }
        ]
        assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1
