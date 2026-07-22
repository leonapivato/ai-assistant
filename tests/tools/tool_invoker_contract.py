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
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

import pytest
from pydantic import ValidationError

from ai_assistant.core.errors import ToolBindingError
from ai_assistant.core.protocols import ToolInvoker, ToolRegistry
from ai_assistant.core.types import (
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

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import FrozenJson
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


class ToolInvokerContract:
    """Behaviour every ``ToolInvoker`` implementation must exhibit."""

    @pytest.fixture
    def invoker(self) -> InvocableToolRegistry:
        """Return an empty invoker under test."""
        raise NotImplementedError

    # --- §1: one registry, two faces ------------------------------------

    async def test_the_invocable_set_is_exactly_all_tools(
        self, invoker: InvocableToolRegistry
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
            result = await invoker.invoke(call_for(each), timeout=PATIENT)
            assert result.outcome is ToolOutcome.SUCCEEDED
            invocable.add(each.id)

        assert invocable == declared == {"alpha", "zulu"}

        unregistered = tool("never-registered")
        with pytest.raises(ToolBindingError):
            await invoker.invoke(call_for(unregistered), timeout=PATIENT)

    async def test_an_unbound_id_is_refused(self, invoker: InvocableToolRegistry) -> None:
        """Nothing is bound, so there is nothing to invoke."""
        with pytest.raises(ToolBindingError, match="smtp"):
            await invoker.invoke(call_for(tool()), timeout=PATIENT)

    async def test_a_tampered_but_still_valid_definition_is_refused(
        self, invoker: InvocableToolRegistry
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
            await invoker.invoke(downgraded, timeout=PATIENT)
        assert spy.calls == [], "the callable must not be reached"

    # --- §2: refused again at the seam ----------------------------------

    async def test_parameters_swapped_after_construction_are_refused(
        self, invoker: InvocableToolRegistry
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
            await invoker.invoke(call, timeout=PATIENT)
        assert spy.calls == []

    async def test_a_replaced_decision_is_refused(self, invoker: InvocableToolRegistry) -> None:
        """A decision about a different payload cannot authorise this one."""
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool(), parameters={"to": "approved@example.com"})
        other = call_for(tool(), parameters={"to": "elsewhere@example.com"}, decision_id="d-2")
        call.__dict__["decision"] = other.decision

        with pytest.raises(ToolBindingError):
            await invoker.invoke(call, timeout=PATIENT)
        assert spy.calls == []

    async def test_a_substituted_definition_is_refused(
        self, invoker: InvocableToolRegistry
    ) -> None:
        """The declaration on the call is rewritten after it was authorised."""
        spy = Spy()
        invoker.register(tool(risk_level=RiskLevel.CRITICAL), spy)
        call = call_for(tool(risk_level=RiskLevel.CRITICAL))

        object.__setattr__(call.request.tool, "risk_level", RiskLevel.LOW)

        with pytest.raises(ToolBindingError):
            await invoker.invoke(call, timeout=PATIENT)
        assert spy.calls == []

    async def test_a_malformed_parameter_mutation_is_a_binding_error_from_revalidation(
        self, invoker: InvocableToolRegistry
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
            await invoker.invoke(call, timeout=PATIENT)

        assert isinstance(caught.value.__cause__, ValidationError), (
            "a malformed mutation must be rejected by revalidation, not by the digest"
        )
        assert spy.calls == []

    # --- §4: the deadline -----------------------------------------------

    async def test_a_side_effecting_non_natural_tool_that_times_out_is_indeterminate(
        self, invoker: InvocableToolRegistry
    ) -> None:
        """ADR-0014 §4's case, reached through a deadline rather than a crash."""
        invoker.register(tool(), Slow())

        result = await invoker.invoke(call_for(tool()), timeout=BRIEF)

        assert result.outcome is ToolOutcome.INDETERMINATE
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.TIMED_OUT
        assert result.output is None

    @pytest.mark.parametrize("definition", [read_only(), natural()], ids=["read-only", "natural"])
    async def test_a_read_only_or_natural_tool_that_times_out_is_failed(
        self, invoker: InvocableToolRegistry, definition: ToolDefinition
    ) -> None:
        """A read changed nothing; a ``NATURAL`` repeat does the same thing again."""
        invoker.register(definition, Slow())

        result = await invoker.invoke(call_for(definition), timeout=BRIEF)

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
            await invoker.invoke(call_for(tool()), timeout=bad)  # type: ignore[arg-type]
        assert spy.calls == []

    async def test_a_tool_that_suppresses_its_cancellation_outlives_its_deadline(
        self, invoker: InvocableToolRegistry
    ) -> None:
        """The cooperative limit, deterministically (ADR-0029 §4).

        "Timeout" here means the seam stops waiting, not that the tool stops
        working — and no seam can make it stronger, because ``asyncio.timeout``
        does not return until the inner frame finishes unwinding. Pinning the
        limit is what stops an implementation quietly acquiring a watchdog.
        """
        stubborn = Stubborn()
        invoker.register(tool(), stubborn)

        running = asyncio.ensure_future(invoker.invoke(call_for(tool()), timeout=BRIEF))
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
        self, invoker: InvocableToolRegistry
    ) -> None:
        """Integration authors raise; a seam that let that propagate would leave
        the step durably ``RUNNING`` with nothing recording why.
        """
        invoker.register(tool(), Raiser(RuntimeError("upstream said no")))

        result = await invoker.invoke(call_for(tool()), timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        assert result.failure.kind.retryable is False

    async def test_the_exceptions_own_text_never_reaches_the_failure_message(
        self, invoker: InvocableToolRegistry
    ) -> None:
        """The message-leak rule (§3), which nothing downstream would catch.

        ``core/logging.py`` redacts by *key* and names ``error=str(exc)`` as the
        Tier 1 leak it cannot see. ``message`` lands under precisely such a key,
        in a log and in ``StepExecution.error``, so the rule has to hold at the
        producer: a message the seam generates carries no content it did not
        author.
        """
        invoker.register(tool(), Raiser(RuntimeError("recipient alice@example.com rejected")))

        result = await invoker.invoke(call_for(tool()), timeout=PATIENT)

        assert result.failure is not None
        assert "alice@example.com" not in result.failure.message
        assert "rejected" not in result.failure.message
        assert "RuntimeError" in result.failure.message

    @pytest.mark.parametrize("value", [{"a", "set"}, float("nan")], ids=["set", "nan"])
    async def test_a_return_value_frozen_json_refuses_becomes_internal(
        self, invoker: InvocableToolRegistry, value: object
    ) -> None:
        """A tool whose return value will not validate is broken, and saying so
        is more useful than storing something unserialisable — or than letting a
        ``ValidationError`` escape a method that returns classified data.
        """
        invoker.register(tool(), Returner(value))

        result = await invoker.invoke(call_for(tool()), timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL

    async def test_a_tools_own_timeout_error_inside_the_deadline_is_internal(
        self, invoker: InvocableToolRegistry
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

        result = await invoker.invoke(call_for(tool()), timeout=PATIENT)

        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        assert result.outcome is ToolOutcome.FAILED

    async def test_a_base_exception_propagates_rather_than_becoming_a_result(
        self, invoker: InvocableToolRegistry
    ) -> None:
        """A guard whose own failure modes bypass its failure path enforces nothing."""
        invoker.register(tool(), Raiser(KeyboardInterrupt()))

        with pytest.raises(KeyboardInterrupt):
            await invoker.invoke(call_for(tool()), timeout=PATIENT)

    # --- §4: cancellation, classified by provenance ----------------------

    async def test_a_cancelled_error_the_tool_invents_is_an_internal_result(
        self, invoker: InvocableToolRegistry
    ) -> None:
        """Nothing about the exception's type says where it came from.

        A tool raising one before it issues its request would otherwise read as
        an external teardown: the executor would record ``INDETERMINATE`` for a
        call that did nothing, and re-raise — cancelling a request nobody
        cancelled, on a tool's say-so. Paired with the next test, this is what
        pins the classification to provenance rather than to the type.
        """
        invoker.register(tool(), Raiser(asyncio.CancelledError()))

        result = await invoker.invoke(call_for(tool()), timeout=PATIENT)

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
        self, invoker: InvocableToolRegistry, definition: ToolDefinition
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

        running = asyncio.ensure_future(invoker.invoke(call_for(definition), timeout=PATIENT))
        await slow.entered.wait()
        running.cancel()

        with pytest.raises(asyncio.CancelledError):
            await running

    async def test_a_tool_that_absorbs_its_deadline_is_not_reported_successful(
        self, invoker: InvocableToolRegistry
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

        result = await invoker.invoke(call_for(tool()), timeout=BRIEF)

        assert swallower.swallowed, "the fixture must actually absorb the cancellation"
        assert result.outcome is ToolOutcome.INDETERMINATE
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.TIMED_OUT

    async def test_a_tool_that_absorbs_an_external_cancellation_still_cancels_the_call(
        self, invoker: InvocableToolRegistry
    ) -> None:
        """A cancelled task must not be answered with a result.

        The cancellation was requested of the *invoking task*, and a callable
        catching it does not withdraw the request. Returning normally here would
        report a cancelled turn as ``SUCCEEDED`` and leave the executor with no
        cancellation to commit against or re-raise (ADR-0029 §4).
        """
        swallower = Swallower()
        invoker.register(tool(), swallower)

        running = asyncio.ensure_future(invoker.invoke(call_for(tool()), timeout=PATIENT))
        await swallower.entered.wait()
        running.cancel()

        with pytest.raises(asyncio.CancelledError):
            await running
        assert swallower.swallowed

    # --- §5: the key is the authorisation --------------------------------

    async def test_a_keyed_tool_receives_the_decision_id_as_its_key(
        self, invoker: InvocableToolRegistry
    ) -> None:
        """Derived, not minted: there is no caller field to fill in wrongly."""
        spy = Spy()
        invoker.register(keyed(), spy)

        await invoker.invoke(call_for(keyed(), decision_id="d-42"), timeout=PATIENT)

        assert [key for _, key in spy.calls] == ["d-42"]

    @pytest.mark.parametrize(
        "definition", [tool(), natural()], ids=["idempotency-none", "idempotency-natural"]
    )
    async def test_a_tool_that_is_not_keyed_receives_no_key(
        self, invoker: InvocableToolRegistry, definition: ToolDefinition
    ) -> None:
        """A key is meaningless to a tool that made no guarantee about one."""
        spy = Spy()
        invoker.register(definition, spy)

        await invoker.invoke(call_for(definition), timeout=PATIENT)

        assert [key for _, key in spy.calls] == [None]

    async def test_the_key_is_identical_across_retries_of_one_call(
        self, invoker: InvocableToolRegistry
    ) -> None:
        """There is deliberately no attempt counter: a key that varied per
        attempt would defeat the guarantee at exactly the moment it is needed.
        """
        spy = Spy()
        invoker.register(keyed(), spy)
        call = call_for(keyed(), decision_id="d-7")

        await invoker.invoke(call, timeout=PATIENT)
        await invoker.invoke(call, timeout=PATIENT)

        assert [key for _, key in spy.calls] == ["d-7", "d-7"]

    async def test_two_decisions_about_identical_parameters_derive_different_keys(
        self, invoker: InvocableToolRegistry
    ) -> None:
        """A fresh authorisation is a fresh action, not a duplicate of the old one."""
        spy = Spy()
        invoker.register(keyed(), spy)
        payload = {"to": "someone@example.com"}

        await invoker.invoke(
            call_for(keyed(), parameters=payload, decision_id="d-1"), timeout=PATIENT
        )
        await invoker.invoke(
            call_for(keyed(), parameters=payload, decision_id="d-2"), timeout=PATIENT
        )

        assert [key for _, key in spy.calls] == ["d-1", "d-2"]

    async def test_the_key_is_reproducible_from_the_decision_alone_after_a_restart(
        self, invoker: InvocableToolRegistry
    ) -> None:
        """The property that makes the key worth anything.

        A restarted executor reads ``StepExecution.approval_ref``, loads *that*
        decision from the durable trail, rebuilds the request, and derives the
        identical key. A key held only in memory would be lost by precisely the
        crash it exists to survive — so this reloads the decision through a JSON
        round-trip rather than reusing the object.
        """
        spy = Spy()
        invoker.register(keyed(), spy)
        before = call_for(keyed(), decision_id="d-99")
        await invoker.invoke(before, timeout=PATIENT)

        reloaded = PermissionDecision.model_validate(before.decision.model_dump(mode="json"))
        after = ToolCall(request=before.request, decision=reloaded)
        await invoker.invoke(after, timeout=PATIENT)

        assert after.idempotency_key == before.idempotency_key
        assert [key for _, key in spy.calls] == ["d-99", "d-99"]

    async def test_a_keyed_tool_deduplicates_inside_its_window_and_acts_again_outside_it(
        self, invoker: InvocableToolRegistry
    ) -> None:
        """The tool's half of ADR-0029 §5's two-sided obligation.

        The executor's half — stopping once the window has elapsed, and treating
        any reading that is not a positive elapsed duration as *lapsed* — is an
        obligation on `orchestration`'s executor and is not observable here.
        """
        window = timedelta(hours=1)
        deduplicating = KeyedTool(window)
        invoker.register(keyed(window=window), deduplicating)
        call = call_for(keyed(window=window), decision_id="d-5")

        first = await invoker.invoke(call, timeout=PATIENT)
        inside = await invoker.invoke(call, timeout=PATIENT)
        deduplicating.now = AT + window + timedelta(seconds=1)
        outside = await invoker.invoke(call, timeout=PATIENT)

        assert first.output == inside.output == 1
        assert outside.output == 2
        assert deduplicating.effects == 2

    # --- success ---------------------------------------------------------

    async def test_a_successful_call_returns_its_output_and_the_tools_arguments(
        self, invoker: InvocableToolRegistry
    ) -> None:
        """The happy path, and that the callable receives what was authorised."""
        spy = Spy(output={"message_id": "m-1"})
        invoker.register(tool(), spy)

        result = await invoker.invoke(
            call_for(tool(), parameters={"to": "someone@example.com"}), timeout=PATIENT
        )

        assert result.outcome is ToolOutcome.SUCCEEDED
        assert result.failure is None
        assert result.output == {"message_id": "m-1"}
        assert spy.calls == [({"to": "someone@example.com"}, None)]
