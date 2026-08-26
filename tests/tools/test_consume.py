"""The consume's `tools/`-internal half (ADR-0192 §1, §3, §5).

The shared conformance suite covers everything the consume is observably
required to do through ``invoke``, on both implementations. What is here is what
only *this* one can be held to, or what ``invoke``'s own surface cannot reach:

* the **callable-shape pairing check's ordering against the claim**. Which
  callable a declaration binds is `tools/`-internal and contracted nowhere
  (ADR-0152 §10), and the canonical fake binds one shape, so this check exists
  here alone — and ADR-0192 §1 moves it **above** the claim rather than leaving
  it where an implementation happened to have put it.
* the ``ToolResult`` → ``ToolInvocation`` **cost mapping** for a result that
  carries a figure. Nothing populates ``ToolResult.incurred_cost`` yet (#1558),
  so no call through ``invoke`` can produce one; the mapping is driven at
  :func:`~ai_assistant.tools.consume.consumed_call`, which is the boundary
  ADR-0192 §5 actually decides.
* that the two copies of the diagnostic's enumerated field values — this
  subsystem's and the canonical fake's — have not drifted apart.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from egress_transport_harness import arguments, binding
from tool_invoker_contract import (
    PATIENT,
    DrivenLedger,
    Spy,
    call_for,
    keyed,
    rows,
    tool,
)

from ai_assistant.core.errors import (
    AuthorisationSpentError,
    ToolBindingError,
    ToolRegistrationError,
    UnrecordedAuthorisationError,
)
from ai_assistant.core.types import (
    ActionRequest,
    CostBasis,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ToolCall,
    ToolCost,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.testing import FakeAuditTrail
from ai_assistant.testing import invoker as fake_invoker
from ai_assistant.tools import consume
from ai_assistant.tools.registry import InMemoryToolRegistry

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import EgressBinding, FrozenJson

AT = call_for(tool()).decision.decided_at


class BoundSpy:
    """An **egress** callable: it takes the binding the ruling fixed (ADR-0148 §4)."""

    def __init__(self) -> None:
        """Record nothing yet."""
        self.calls: list[EgressBinding] = []

    async def invoke_bound(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
        egress_binding: EgressBinding,
    ) -> FrozenJson:
        """Record the binding it was handed and succeed."""
        self.calls.append(egress_binding)
        return None


def call_carrying(definition: object, bound: EgressBinding | None) -> ToolCall:
    """An authorised call for ``definition``, carrying ``bound`` or nothing.

    The parameters are the harness's, so a binding's spans name arguments the
    call actually carries — the invariant ``ActionRequest`` enforces, which is
    beside the point here and would otherwise decide the case before the seam
    saw it.
    """
    request = ActionRequest(
        tool=definition,  # type: ignore[arg-type]  # the builder's own type
        parameters=arguments(),
        step_id="step-1",
        egress_binding=bound,
    )
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="because it is allow"),
        id="d-1",
        decided_at=AT,
    )
    return ToolCall(request=request, decision=decision)


@pytest.mark.parametrize("shape", ["egress-callable-without-a-binding", "plain-callable-with-one"])
async def test_the_pairing_check_refuses_before_any_claim_is_appended(shape: str) -> None:
    """ADR-0192 §1's floor is not the whole ordering, and this is the check it adds.

    An implementation claiming first passes every other case in the suite and
    then owes ADR-0192 §3 a completion carrying an outcome ADR-0029 computes for
    no ``ToolBindingError`` — that error is given no ``ToolResult`` at all, only
    the executor's ``FAILED`` step. So the trail holds no invocation row for that
    decision afterwards, the callable is never entered, and no completion is
    attempted.
    """
    trail = FakeAuditTrail()
    ledger = DrivenLedger(trail)
    if shape == "egress-callable-without-a-binding":
        implementation: object = BoundSpy()
        call = call_carrying(tool(), None)
    else:
        implementation = Spy()
        call = call_carrying(tool(), binding())
    registry = InMemoryToolRegistry(
        [(tool(), implementation)],  # type: ignore[list-item]  # the doubles' own shapes
        ledger=ledger,
        gate=FakeAuditTrail(),
    )
    await trail.record(call.decision)

    with pytest.raises(ToolBindingError):
        await registry.invoke(call, timeout=PATIENT)

    assert implementation.calls == [], "the callable is never entered"  # type: ignore[attr-defined]
    assert ledger.claim.calls == 0, "no claim is appended for a seam fault"
    assert ledger.completion.calls == 0
    assert await rows(trail) == []


async def test_a_reported_cost_maps_onto_the_row_unaltered() -> None:
    """ADR-0192 §5's boundary, driven where the mapping actually is.

    Not through ``invoke``: ``ToolImplementation`` returns ``FrozenJson`` and no
    ADR owns minting a carrier, so a case asserting a figure traversing the
    production path would have to construct a ``ToolResult`` past the seam or
    patch inside it — proving the mapping this drives and proving nothing about
    the path. The end-to-end case is owed by whichever ADR answers #1558.
    """
    trail = FakeAuditTrail()
    call = call_for(tool())
    await trail.record(call.decision)
    reported = ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.02"), currency="USD")

    async def act() -> ToolResult:
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, incurred_cost=reported)

    await consume.consumed_call(ledger=trail, definition=tool(), decision=call.decision, act=act)

    (completion,) = [each for each in await rows(trail) if each.completes is not None]
    assert completion.incurred_cost == reported


def test_the_two_copies_of_the_diagnostics_vocabulary_agree() -> None:
    """The fake re-implements the consume, so the enumerated values are duplicated.

    They are the fields an operator's alerting keys on, and a drift between the
    two would be invisible to every behavioural case in the suite: each
    implementation would report its own vocabulary consistently.
    """
    assert (consume.CLAIM, consume.COMPLETION, consume.APPEND_FAILED) == (
        fake_invoker.CLAIM,
        fake_invoker.COMPLETION,
        fake_invoker.APPEND_FAILED,
    )


class Watchful:
    """An **egress** callable that counts every read of ``invoke_bound``.

    Fetching the bound method is an attribute access on an object this seam did
    not write, so it runs that object's own ``__getattribute__``. This one only
    counts; a hostile one would transmit. (The ``isinstance`` against the
    ``runtime_checkable`` Protocol does *not* — since 3.12 it resolves through
    ``inspect.getattr_static`` — so the fetch is the whole of the exposure, and it
    happens only for a registration that already has the shape.)
    """

    def __init__(self) -> None:
        """Record nothing yet."""
        object.__setattr__(self, "shape_reads", 0)
        object.__setattr__(self, "calls", 0)

    def __getattribute__(self, name: str) -> object:
        if name == "invoke_bound":
            # `object.__getattribute__` throughout, so the counter does not
            # recurse back through this method.
            reads = object.__getattribute__(self, "shape_reads")
            object.__setattr__(self, "shape_reads", reads + 1)
        return object.__getattribute__(self, name)

    async def invoke_bound(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
        egress_binding: EgressBinding,
    ) -> FrozenJson:
        """Record the entry and succeed."""
        object.__setattr__(self, "calls", object.__getattribute__(self, "calls") + 1)
        return None


def _reads(watchful: Watchful) -> int:
    """Read the counter without going through the counting ``__getattribute__``."""
    read: int = object.__getattribute__(watchful, "shape_reads")
    return read


async def test_a_refused_claim_reaches_no_code_the_implementation_owns() -> None:
    """The shape is read at registration, so an invocation reads nothing off the object.

    ADR-0192 §1 puts the pairing check above the claim, and part of that check is
    fetching the registration's bound method — an attribute access that runs the
    implementation's own ``__getattribute__``. Performed per call it would run
    **before** the claim, so a call the ledger then refused
    ``UnrecordedAuthorisationError`` would already have reached the
    implementation's code, with no invocation row anywhere to say so.

    Performed at registration it runs once, at composition time, under no
    authorisation and with no decision to run ahead of — and ADR-0016 §5 already
    binds an id to *that* callable for the life of the process, so there is
    nothing later to re-read. The counter is the whole assertion: it moves when
    the tool is registered, and never again.
    """
    trail = FakeAuditTrail()
    watchful = Watchful()
    call = call_carrying(tool(), binding())
    registry = InMemoryToolRegistry([(tool(), watchful)], ledger=trail, gate=trail)

    at_registration = _reads(watchful)
    assert at_registration == 1, "the shape is decided once, when the callable is registered"

    # Never recorded, so the ledger refuses this claim.
    with pytest.raises(UnrecordedAuthorisationError):
        await registry.invoke(call, timeout=PATIENT)

    assert _reads(watchful) == at_registration, (
        "a refused claim reached no code the implementation owns"
    )
    assert object.__getattribute__(watchful, "calls") == 0
    assert await rows(trail) == []


class OneRead:
    """An **egress** callable whose ``invoke_bound`` may be read exactly once."""

    def __init__(self) -> None:
        """Allow one read."""
        object.__setattr__(self, "reads", 0)

    def __getattribute__(self, name: str) -> object:
        if name == "invoke_bound":
            reads = object.__getattribute__(self, "reads")
            if reads:
                msg = "the shape may be read only once"
                raise RuntimeError(msg)
            object.__setattr__(self, "reads", reads + 1)
        return object.__getattribute__(self, name)

    async def invoke_bound(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
        egress_binding: EgressBinding,
    ) -> FrozenJson:
        """Succeed."""
        return None


def test_an_identical_re_registration_resolves_nothing_a_second_time() -> None:
    """Idempotency has to survive the shape being decided at registration.

    A composition root may run twice, so re-registering the *same* definition and
    the *same* object is contracted to do nothing (ADR-0016 §5). Deciding the
    callable's shape reads ``invoke_bound`` off that object — arbitrary code —
    so resolving before finding out there is nothing to do would run it again,
    and an object that tolerates one read would refuse the second.

    The duplicate is therefore answered from the registry's own record, before
    anything is read.
    """
    implementation = OneRead()
    registry = InMemoryToolRegistry(
        [(tool(), implementation)], ledger=FakeAuditTrail(), gate=FakeAuditTrail()
    )
    assert object.__getattribute__(implementation, "reads") == 1

    registry.register(tool(), implementation)

    assert object.__getattribute__(implementation, "reads") == 1, (
        "the identical registration is answered from the record, reading nothing again"
    )


class NotQuiteEgress:
    """An ordinary callable carrying a **non-callable** ``invoke_bound``.

    ``runtime_checkable`` resolves the member through ``inspect.getattr_static``,
    which finds the **property object** and asks no further, so this reports as an
    ``EgressToolImplementation`` while being an ordinary tool. (A plain
    ``invoke_bound = None`` would not: since 3.12 a ``None``-valued member fails
    the check outright, which is why the property is what this drives.)
    """

    def __init__(self) -> None:
        """Record nothing yet."""
        self.calls = 0

    @property
    def invoke_bound(self) -> None:
        """Present, and not a method."""
        return None

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
    ) -> FrozenJson:
        """Record the entry and succeed."""
        self.calls += 1
        return None


async def test_a_presence_only_egress_shape_is_bound_as_the_ordinary_callable() -> None:
    """Presence is not a callable, and the difference must not surface after the claim.

    An implementation whose ``invoke_bound`` is a data attribute or a property
    returning ``None`` satisfies the structural check and has nothing to enter. A
    seam that stored that shape on trust would discover it at the point of entry
    — after the claim — where ADR-0192 §1 permits no fault at all and ADR-0029
    computes no outcome for one. So callability decides: this is an ordinary
    callable, it is entered as one, and the call succeeds.
    """
    trail = FakeAuditTrail()
    implementation = NotQuiteEgress()
    registry = InMemoryToolRegistry([(tool(), implementation)], ledger=trail, gate=trail)
    call = call_for(tool())
    await trail.record(call.decision)

    result = await registry.invoke(call, timeout=PATIENT)

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert implementation.calls == 1, "the ordinary shape is what was entered"
    assert await trail.open_invocations(decision_id=call.decision.id) == []


def test_an_object_satisfying_neither_shape_is_refused_at_registration() -> None:
    """And where nothing is callable, the refusal is a registration error.

    The alternative is a binding with nothing to enter, whose failure would land
    after the claim. ADR-0016 §5 owns what may be bound to an id; this is that
    question answered where it belongs.
    """
    with pytest.raises(ToolRegistrationError, match="neither tool shape"):
        InMemoryToolRegistry([(tool(), object())], ledger=FakeAuditTrail(), gate=FakeAuditTrail())  # type: ignore[list-item]  # the refusal is the subject


class Shifty:
    """An ordinary callable that acquires the **egress** shape mid-claim.

    ``EgressToolImplementation`` is ``runtime_checkable``, so the shape is an
    attribute an object can grow while the seam is awaiting something — which is
    the only way a second reading of it could disagree with the first.
    """

    def __init__(self) -> None:
        """Start out as an ordinary callable."""
        self.calls = 0

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
    ) -> FrozenJson:
        """Record the entry and succeed."""
        self.calls += 1
        return None

    def become_an_egress_callable(self) -> None:
        """Grow ``invoke_bound``, so a later ``isinstance`` reads a different shape."""
        self.invoke_bound = self.__call__


async def test_the_callables_shape_is_resolved_once_and_never_read_after_the_claim() -> None:
    """ADR-0192 §1's property, tested against the only thing that can falsify it.

    "After the claim, ``invoke`` performs no check that can raise a seam fault" is
    stated as a **property, not a list**, so it is not enough that no *ordinary*
    input reaches a post-claim check. Here the callable grows ``invoke_bound``
    while the claim append is held: a seam that read the shape again would raise
    ``ToolBindingError`` after the claim — an exit ADR-0029 computes no outcome
    for, leaving the claim open under a step ADR-0034 §1 commits ``FAILED`` and no
    scan ever returns for.
    """
    trail = FakeAuditTrail()
    ledger = DrivenLedger(trail)
    ledger.claim.hold = asyncio.Event()
    shifty = Shifty()
    registry = InMemoryToolRegistry([(tool(), shifty)], ledger=ledger, gate=FakeAuditTrail())
    call = call_for(tool())
    await trail.record(call.decision)

    task = asyncio.create_task(registry.invoke(call, timeout=PATIENT))
    await ledger.claim.entered.wait()
    shifty.become_an_egress_callable()
    ledger.claim.hold.set()
    result = await task

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert shifty.calls == 1, "the shape resolved before the claim is the one that ran"
    assert [each.completes is not None for each in await rows(trail)].count(True) == 1
    assert await trail.open_invocations(decision_id=call.decision.id) == []


def unavailable() -> ToolResult:
    """A ``FAILED`` result whose kind is a **retryable** one (ADR-0029 §5)."""
    return ToolResult(
        outcome=ToolOutcome.FAILED,
        failure=ToolFailure(kind=ToolFailureKind.UNAVAILABLE, message="the upstream is down"),
    )


async def test_a_retryable_failure_on_a_spendable_keyed_call_admits_the_retry() -> None:
    """ADR-0192 §9's retry arm, driven at the boundary where it is constructible.

    **Not through ``invoke``, and that is a property of the tree rather than a
    choice.** The seam produces exactly two failure shapes: a raising callable
    becomes ``FAILED``/``INTERNAL``, which is not retryable, and an expired
    deadline becomes ``interrupted_outcome``/``TIMED_OUT`` — and
    ``interrupted_outcome`` is ``FAILED`` exactly when the tool is **not**
    *spendable*, the precise complement of §1's discriminator. So on a spendable
    authorisation the deadline always yields ``INDETERMINATE``, which spends, and
    "a retryable ``FAILED`` on a spendable ``KEYED`` authorisation" has no
    producer through ``invoke`` today.

    **The carrier that would give it one is ADR-0032's, not #1558's**, and the
    distinction matters because the two answer different halves: #1558 is
    ADR-0192 §5's *cost* transport, while ADR-0032 §1 mints ``ClassifiedToolError``
    as the **failure** transport — "a tool reporting a failure it classified
    itself … caught by ``ToolInvoker.invoke``, which turns it into a
    ``ToolResult``". That ADR is Accepted and **unimplemented**: the symbol
    appears nowhere under ``src/``, which is what issue #596 records. So the case
    is owed by ADR-0032's implementation lane, and is tracked on #1583.

    What is constructible is the boundary ADR-0192 §5 and §2 actually decide, and
    it carries the whole of what §9's clause is for: the kind is **transcribed**
    onto the completion rather than dropped, and the ledger then admits a further
    claim inside the window. An implementation dropping ``failure_kind`` for a
    keyed side-effecting ``FAILED`` produces a valid kindless completion that
    silently refuses a legitimate retry as spent — which this case fails on.
    """
    trail = FakeAuditTrail()
    call = call_for(keyed())
    await trail.record(call.decision)

    async def act() -> ToolResult:
        return unavailable()

    first = await consume.consumed_call(
        ledger=trail, definition=keyed(), decision=call.decision, act=act
    )

    assert first.outcome is ToolOutcome.FAILED
    (completion,) = [each for each in await rows(trail) if each.completes is not None]
    assert completion.outcome is ToolOutcome.FAILED
    assert completion.failure_kind is ToolFailureKind.UNAVAILABLE, "the kind is not dropped"
    assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)

    # §1's conjunction is satisfied — no claim open, none carrying `SUCCEEDED` or
    # `INDETERMINATE`, the last completed `FAILED` with a retryable kind, `KEYED`,
    # inside the window — so the further claim is admitted.
    await consume.consumed_call(ledger=trail, definition=keyed(), decision=call.decision, act=act)

    assert len([each for each in await rows(trail) if each.completes is None]) == 2


async def test_the_same_sequence_refuses_the_retry_where_the_completion_did_not_commit() -> None:
    """The twin, differing in **one fact**: whether the completion append landed.

    ADR-0192 §1 states it positively rather than leaving it to be composed out of
    the conjunction — an open claim refuses a further act, so completion
    durability is a third prerequisite for ADR-0029 §5's retry. Both of §5's own
    conditions hold here and the retry is nonetheless refused, twice over: a claim
    under that decision is open, and the last claim in the append order is that
    same open one and so is not completed ``FAILED`` at all.
    """
    trail = FakeAuditTrail()
    ledger = DrivenLedger(trail)
    ledger.completion.error = RuntimeError("the store would not write")
    call = call_for(keyed())
    await trail.record(call.decision)

    async def act() -> ToolResult:
        return unavailable()

    returned = await consume.consumed_call(
        ledger=ledger, definition=keyed(), decision=call.decision, act=act
    )

    assert returned.outcome is ToolOutcome.FAILED, "the act's own result stands"
    assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1

    with pytest.raises(AuthorisationSpentError):
        await consume.consumed_call(
            ledger=ledger, definition=keyed(), decision=call.decision, act=act
        )

    assert len(await rows(trail)) == 1, "one claim, still open, and no completion"
